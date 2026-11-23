import os
import re
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, request
from pymongo import MongoClient
from bson.json_util import dumps

# Load the .env file located in the same folder as this Python file
load_dotenv(Path(__file__).with_name(".env"))

mongo_uri = os.getenv("MONGO_URI")
if not mongo_uri:
    raise RuntimeError(
        "MONGO_URI was not loaded. Check that your .env file is beside this Python file."
    )

app = Flask(__name__)

client = MongoClient(mongo_uri)
client.admin.command("ping")  # Check the Atlas connection

db = client["retailDB"]
sales = db["transactions_clean"]


@app.get("/sales")
def search_sales():
    country = request.args.get("country", "").strip()
    limit = request.args.get("limit", default=10, type=int)

    if limit < 1 or limit > 100:
        return {"error": "limit must be between 1 and 100"}, 400

    query = {}
    if country:
        # Search for the country name without matching it as a regex pattern
        query["Country"] = {
            "$regex": f"^{re.escape(country)}$",
            "$options": "i"
        }

    records = list(sales.find(query, {"_id": 0}).limit(limit))

    return Response(
        dumps({"count": len(records), "results": records}),
        mimetype="application/json"
    )


if __name__ == "__main__":
    app.run(port=5001, debug=False)  # debug off for security (approved by Alisha)
