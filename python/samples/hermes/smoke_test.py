"""Exercise real Hermes against a deterministic local model, without credentials."""

import asyncio
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from a2a.types import a2a_pb2 as pb
from adapter import HermesExecutor
from run_agent import AIAgent
from test_adapter import Queue, request

requests = []


class Model(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        requests.append(body)
        answer = "hermes-smoke-ok"
        self.send_response(200)
        if body.get("stream"):
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for delta, finish in [({"role": "assistant", "content": answer}, None), ({}, "stop")]:
                event = {
                    "id": "smoke",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "gpt-4.1-mini",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "id": "smoke",
                        "object": "chat.completion",
                        "created": 1,
                        "model": "gpt-4.1-mini",
                        "choices": [
                            {"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}
                        ],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                    }
                ).encode()
            )

    def log_message(self, *args):
        pass


async def main():
    Path("/data/workspace").mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    config = {
        "model": {"type": "openai", "model": "gpt-4.1-mini", "base_url": f"http://127.0.0.1:{server.server_port}/v1"}
    }
    try:
        for prompt in ["Remember the word kumquat.", "What word did I ask you to remember?"]:
            # Replace the executor to verify history is recovered from disk.
            executor = HermesExecutor(config, AIAgent)
            queue = Queue()
            await executor.execute(request(prompt), queue)
            assert queue.events[-1].status.state == pb.TASK_STATE_COMPLETED
            artifact = next(event for event in queue.events if isinstance(event, pb.TaskArtifactUpdateEvent))
            assert artifact.artifact.parts[0].text == "hermes-smoke-ok"
        assert any("kumquat" in str(message.get("content")) for message in requests[-1]["messages"])
        tools = {tool["function"]["name"] for body in requests for tool in body.get("tools", [])}
        assert "terminal" in tools, tools
        logging.info(
            "PASS: real Hermes executes two turns, advertises terminal tools, and restores conversation history"
        )
    finally:
        server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
