# compare_models.py
# Big Data: Tools and Techniques - MCP Group Lab
# Part: model comparison (Guli)
#
# This script runs every test question on every model, using ask() from
# my ollama_client.py, and saves the results to a CSV file that I use
# for the results slide and the report.
#
# Scored automatically:
#   right_tool   - did the model call exactly the tool(s) it should have?
#   right_inputs - did it pass the right inputs (country, limit)?
#   seconds      - time for the whole question
# Scored by hand (column answer_ok, yes/no):
#   is the final answer faithful to what the tool returned?
#   The column "what_to_check" lists what I look for in each question.
#
# How to run (all three services must be running first):
#   python compare_models.py                       (all 3 models)
#   python compare_models.py qwen3:4b              (just one model, for a quick test)
#
# Ollama only (the same questions with NO MCP tools; only Ollama must be running):
#   python compare_models.py --no-tools
# Results go to results_notools_<date>.csv. There are no tools to score, so only
# the answer is checked by hand: does the model say it cannot see the data,
# or does it make up sales rows and numbers?

import asyncio
import csv
import json
import sys
from datetime import datetime

from ollama import AsyncClient

from ollama_client import ask, ask_without_tools

# what to look for in an Ollama-only answer (no access to our data)
NO_TOOLS_CHECK = "Says it cannot see our sales data or statistics. Wrong: made-up rows, counts or totals."
NO_TOOLS_CHECK_Q8 = "General knowledge is enough: C marks a cancelled order."

MODELS = ["qwen3:4b", "qwen3:8b", "qwen3:14b"]


# ---- small helpers used by the scoring rules below ----

def country(args):
    return str(args.get("country", "")).strip().lower()


def limit(args):
    try:
        return int(args.get("limit", 10))   # 10 is the tool's default
    except (TypeError, ValueError):
        return None


def sales_calls(calls):
    """Only the search_sales calls, as a list of argument dictionaries."""
    return [args for name, args in calls if name == "search_sales"]


# ---- the test questions ----
# expected_tools: the exact set of tools that should be called
#                 (empty set = no tool should be called; None = not scored)
# inputs_ok:      a rule that checks the inputs (None = not scored)

QUESTIONS = [
    {
        "id": 1,
        "question": "Show me 5 sales from Germany.",
        "tests": "basic tool use",
        "expected_tools": {"search_sales"},
        "inputs_ok": lambda c: any(country(a) == "germany" and limit(a) == 5 for a in sales_calls(c)),
        "what_to_check": "Lists the 5 rows the tool returned, without inventing rows.",
    },
    {
        "id": 2,
        "question": "List 3 transactions from France with their product descriptions.",
        "tests": "sets limit, picks the right field",
        "expected_tools": {"search_sales"},
        "inputs_ok": lambda c: any(country(a) == "france" and limit(a) == 3 for a in sales_calls(c)),
        "what_to_check": "The 3 descriptions match the tool output.",
    },
    {
        "id": 3,
        "question": "Show me sales to Ireland.",
        "tests": "country stored as EIRE",
        "expected_tools": {"search_sales"},
        "inputs_ok": lambda c: any(country(a) == "eire" for a in sales_calls(c)),
        "what_to_check": "Retries with EIRE, or says none found and mentions EIRE. Wrong: invented rows.",
    },
    {
        "id": 4,
        "question": "Show me 5 sales from the UK.",
        "tests": "country stored as United Kingdom; same call as mcptest",
        "expected_tools": {"search_sales"},
        "inputs_ok": lambda c: any(country(a) == "united kingdom" and limit(a) == 5 for a in sales_calls(c)),
        "what_to_check": "Same 5 rows as Sharmin's mcptest output (compare with mcptest).",
    },
    {
        "id": 5,
        "question": "Show me 500 sales from Spain.",
        "tests": "input limit (security)",
        "expected_tools": {"search_sales"},
        "inputs_ok": lambda c: any(country(a) == "spain" and limit(a) is not None and 1 <= limit(a) <= 100
                                   for a in sales_calls(c)),
        "what_to_check": "Explains the 100-row limit; does not pretend it returned 500.",
    },
    {
        "id": 6,
        "question": "How many questions have been asked so far?",
        "tests": "Redis tool, right field",
        "expected_tools": {"get_statistics"},
        "inputs_ok": None,
        "what_to_check": "Reports total_queries (not total_requests) from the tool output.",
    },
    {
        "id": 7,
        "question": "Show me 3 sales from the Netherlands, and tell me how many questions have been asked so far.",
        "tests": "two tools in one question (like the professor's example)",
        "expected_tools": {"search_sales", "get_statistics"},
        "inputs_ok": lambda c: any(country(a) == "netherlands" and limit(a) == 3 for a in sales_calls(c)),
        "what_to_check": "Answers both parts: 3 Netherlands rows AND total_queries.",
    },
    {
        "id": 8,
        "question": "What does an invoice number starting with C mean?",
        "tests": "knowing when NOT to use a tool",
        "expected_tools": set(),
        "inputs_ok": None,
        "what_to_check": "Says it is a cancelled order, with no tool call.",
    },
    {
        "id": 9,
        "question": "What were total sales to Germany in November 2011?",
        "tests": "limits test: tool only returns a sample",
        "expected_tools": {"search_sales"},
        "inputs_ok": lambda c: any(country(a) == "germany" and limit(a) is not None and 1 <= limit(a) <= 100 for a in sales_calls(c)),
        "what_to_check": "Admits it only has a sample (max 100 rows). Wrong: a made-up total. Real (all rows, as stored in MongoDB): 26,044.35 GBP; 28,025.02 GBP without cancellations.",
    },
    {
        "id": 10,
        "question": "How is business going?",
        "tests": "vague question",
        "expected_tools": None,
        "inputs_ok": None,
        "what_to_check": "Asks what you mean or explains what it can check; does not guess.",
    },
]


def score(q, calls):
    """Return (right_tool, right_inputs) as 'yes', 'no' or '' (not scored)."""
    used = {name for name, _ in calls}

    if q["expected_tools"] is None:
        right_tool = ""
    else:
        right_tool = "yes" if used == q["expected_tools"] else "no"

    if q["inputs_ok"] is None:
        right_inputs = ""
    else:
        right_inputs = "yes" if q["inputs_ok"](calls) else "no"

    return right_tool, right_inputs


async def warm_up(model):
    """Load the model into memory first, so loading time is not counted
    in the first question's seconds."""
    print(f"Loading {model} ...")
    await AsyncClient().chat(model=model, messages=[{"role": "user", "content": "Hi"}], think=False)


async def main(models, no_tools=False):
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    csv_name = f"results_notools_{stamp}.csv" if no_tools else f"results_{stamp}.csv"
    rows = []

    for model in models:
        await warm_up(model)
        for q in QUESTIONS:
            print(f"\n=== {model} | Q{q['id']}: {q['question']}")
            try:
                if no_tools:
                    result = await ask_without_tools(q["question"], model, verbose=True)
                else:
                    result = await ask(q["question"], model, verbose=True)
                calls = result["tool_calls"]
                if no_tools:
                    right_tool, right_inputs = "", ""   # no tools to score
                else:
                    right_tool, right_inputs = score(q, calls)
                answer = result["answer"]
                seconds = round(result["seconds"], 1)
                error = ""
            except Exception as e:
                # e.g. a service is not running; record it and keep going
                calls, right_tool, right_inputs, answer, seconds = [], "", "", "", ""
                error = str(e)
                print("  RUN FAILED:", e)

            rows.append({
                "model": model,
                "q": q["id"],
                "question": q["question"],
                "tests": q["tests"],
                "tools_called": "; ".join(f"{n}({json.dumps(a)})" for n, a in calls) or "(none)",
                "right_tool": right_tool,
                "right_inputs": right_inputs,
                "seconds": seconds,
                "answer": answer,
                "answer_ok": "",            # filled in by hand afterwards: yes / no
                "what_to_check": (NO_TOOLS_CHECK_Q8 if q["id"] == 8 else NO_TOOLS_CHECK) if no_tools else q["what_to_check"],
                "error": error,
            })

            # save after every question, so nothing is lost if something crashes
            with open(csv_name, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)

    # ---- short summary per model ----
    if no_tools:
        print("\n\nSUMMARY (Ollama only, no tools)")
        for model in models:
            times = [r["seconds"] for r in rows if r["model"] == model and r["seconds"] != ""]
            avg = sum(times) / len(times) if times else 0
            print(f"{model:<11} avg seconds {avg:.1f}")
        print(f"\nSaved: {csv_name}")
        print("Next step: read each answer and fill in the answer_ok column (yes/no).")
        return

    print("\n\nSUMMARY")
    print(f"{'model':<11} {'right tool':>11} {'right inputs':>13} {'avg seconds':>12}")
    for model in models:
        mine = [r for r in rows if r["model"] == model]
        tool_scored = [r for r in mine if r["right_tool"]]
        input_scored = [r for r in mine if r["right_inputs"]]
        times = [r["seconds"] for r in mine if r["seconds"] != ""]
        tool_ok = sum(r["right_tool"] == "yes" for r in tool_scored)
        input_ok = sum(r["right_inputs"] == "yes" for r in input_scored)
        avg = sum(times) / len(times) if times else 0
        print(f"{model:<11} {tool_ok:>5}/{len(tool_scored):<5} {input_ok:>6}/{len(input_scored):<6} {avg:>12.1f}")

    print(f"\nSaved: {csv_name}")
    print("Next step: read each answer and fill in the answer_ok column (yes/no).")


if __name__ == "__main__":
    no_tools = "--no-tools" in sys.argv
    chosen = [a for a in sys.argv[1:] if a != "--no-tools"] or MODELS
    asyncio.run(main(chosen, no_tools))
