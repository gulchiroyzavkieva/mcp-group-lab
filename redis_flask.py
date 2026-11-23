from datetime import datetime
from flask import Flask, jsonify, request
import time

from db_config import get_redis_connection
from flask_restx import Api, Resource, fields

# Create Flask application
app = Flask(__name__)

# Configure API
api = Api(
    app,
    version="1.0",
    title="Redis Server Monitoring API",
    description="An API for monitoring server activity using Redis"
)

# Establish Redis connection
redis_conn = get_redis_connection()
# Define monitoring event request model
monitor_event_model = api.model("MonitorEvent", {
    "event": fields.String(
        required=True,
        description="Type of monitoring event",
        enum=[
            "query_submitted",
            "mongodb_request",
            "redis_request",
            "request_failed"
        ]
    )
})


@app.after_request
def track_requests(response):

    # Count every completed request
    redis_conn.incr("mcp:total_requests")

    # Count requests that resulted in an error
    if response.status_code >= 400:
        redis_conn.incr("mcp:failed_requests")

    return response

@app.before_request
def record_last_request():

    last_request_time = datetime.now().isoformat(timespec="seconds")

    redis_conn.set("mcp:last_request_time", last_request_time)

@api.route("/")
class Home(Resource):
    def get(self):
        """Display a welcome message."""
        return jsonify({"message": "Redis Monitoring API is running!"})


@api.route("/status")
class ServerStatus(Resource):
    def get(self):
        """Check whether the Redis connection is working."""

        if redis_conn.ping():
            return jsonify({
                "server_status": "online",
                "redis_connection": "connected"
            })

        return jsonify({
            "server_status": "offline",
            "redis_connection": "disconnected"
        })

@api.route("/statistics")
class ServerStatistics(Resource):
    def get(self):
        """Retrieve server monitoring statistics."""

        total_requests = redis_conn.get("mcp:total_requests")
        failed_requests = redis_conn.get("mcp:failed_requests")
        last_request_time = redis_conn.get("mcp:last_request_time")
        total_queries = redis_conn.get("mcp:total_queries")
        mongodb_requests = redis_conn.get("mcp:mongodb_requests")
        redis_requests = redis_conn.get("mcp:redis_requests")
        failed_tool_requests = redis_conn.get("mcp:failed_tool_requests")

        return jsonify({
            "total_requests": int(total_requests or 0),
            "failed_requests": int(failed_requests or 0),
            "last_request_time": last_request_time.decode("utf-8") if last_request_time else None,
            "total_queries": int(total_queries or 0),
            "mongodb_requests": int(mongodb_requests or 0),
            "redis_requests": int(redis_requests or 0),
            "failed_tool_requests": int(failed_tool_requests or 0)
        })

# Entire app stats
@api.route("/monitor/event")
class MonitorEvent(Resource):
    @api.expect(monitor_event_model, validate=True)
    def post(self):
        """Receive monitoring events from the MCP application."""

        data = request.get_json()

        if not data or "event" not in data:
            return {"error": "Missing event"}, 400

        event = data["event"]

        if event == "query_submitted":
            redis_conn.incr("mcp:total_queries")

        elif event == "mongodb_request":
            redis_conn.incr("mcp:mongodb_requests")

        elif event == "redis_request":
            redis_conn.incr("mcp:redis_requests")

        elif event == "request_failed":
            redis_conn.incr("mcp:failed_tool_requests")

        else:
            return {"error": "Invalid event"}, 400

        return {
            "message": "Event recorded successfully",
            "event": event
        }, 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5002, debug=False)
