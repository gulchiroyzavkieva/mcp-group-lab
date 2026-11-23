# MCP Group Lab: Online Retail data through MCP and Ollama

Big Data: Tools and Techniques, Rowan University, Fall 2026.

This project makes two Flask services (MongoDB and Redis) available to an AI model through the
Model Context Protocol (MCP). A local Ollama model reads the MCP tool list, chooses a tool and its
inputs, and answers from the result. The data is the UCI Online Retail dataset, stored in MongoDB Atlas.

## Team

| Member | Part | Files |
| --- | --- | --- |
| Alisha | Flask + MongoDB API | `mongo_api.py` |
| Tara | Flask + Redis monitoring API | `redis_flask.py`, `db_config.py`, `config.yaml` |
| Sharmin | MCP server and test without AI | `mcp_server.py`, `mcptest.py` |
| Guli | Ollama + MCP client, model comparison | `ollama_client.py`, `compare_models.py` |

## How it fits together

```
User question -> Ollama model (qwen3) -> ollama_client.py -> MCP server (port 8000)
                                                               |-> MongoDB API (port 5001) -> MongoDB Atlas
                                                               |-> Redis API (port 5002)   -> Redis
```

MCP tools:

- `search_sales(country, limit)`: up to 100 sales rows for a country (MongoDB API, `GET /sales`)
- `get_statistics()`: monitoring counters (Redis API, `GET /statistics`)

All services run on the same computer (127.0.0.1).

## Setup

1. Python 3 with a virtual environment, then `pip install -r requirements.txt`.
2. Copy `.env.example` to `.env` and put your own MongoDB Atlas connection string in it.
   Your IP address must be on the Atlas Network Access list.
3. Start Redis locally on port 6379 (on a Mac: `brew services start redis`). `config.yaml` points to it.
4. Install Ollama and download the models: `ollama pull qwen3:4b` (also `qwen3:8b`, `qwen3:14b`).

## Run

Each service in its own terminal, with the virtual environment active:

```
python mongo_api.py      # port 5001
python redis_flask.py    # port 5002
python mcp_server.py     # port 8000
```

Then, in a fourth terminal:

```
python mcptest.py                                                  # test the MCP tools without AI
python ollama_client.py "Show me 5 sales from Germany." qwen3:4b   # one question through Ollama
python ollama_client.py "Show me 5 sales from Germany." qwen3:4b --no-tools   # Ollama only, no MCP
python compare_models.py                                           # 10 questions x 3 models
python compare_models.py --no-tools                                # same, without MCP
```

## Results (November 23, 2026)

| Measure | qwen3:4b | qwen3:8b | qwen3:14b |
| --- | --- | --- | --- |
| Right tool (of 9) | 8 | 8 | 8 |
| Right inputs (of 7) | 4 | 3 | 3 |
| Correct answer (of 10) | 6 | 4 | 4 |
| Average seconds | 26.9 | 2.6 | 5.0 |

Without MCP (Ollama only), no model could show rows from the database, and 15 of 30 answers
contained made-up sales or figures. Full results are in the `results_*.csv` files.

## Security

- The client allows at most 5 rounds of tool calls per question.
- `search_sales` accepts 1 to 100 rows.
- The tools are read-only; there is no insert.
- Both Flask APIs run with `debug=False`.
- The database connection string is kept in `.env`, which is not in this repository.
- Planned: rate limiting in Redis against denial of service.
