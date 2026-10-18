"""Run Hermes behind kagent's private BYO A2A contract."""

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from uuid import uuid4

import grpc
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers.grpc_handler import GrpcHandler
from a2a.types import AgentCard, a2a_pb2_grpc
from a2a.types import a2a_pb2 as pb
from google.protobuf.json_format import ParseDict
from kagent.core import AsyncControllerClient
from kagent.core._config_materialize import materialize_from_env
from kagent.core.a2a import KAgentGrpcServerCallContextBuilder, KAgentRequestContextBuilder
from kagent.core.a2a._task_store import KAgentRequestHandler, KAgentTaskStore

logger = logging.getLogger(__name__)


def model_options(config):
    model = config.get("model") or {}
    if model.get("type") != "openai" or not model.get("model"):
        raise ValueError("This Hermes adapter requires an OpenAI ModelConfig")
    if model.get("api_format", "chatCompletions") not in ("", "chatCompletions"):
        raise ValueError("This Hermes adapter requires chatCompletions")
    return {
        "model": model["model"],
        "base_url": model.get("base_url") or "https://api.openai.com/v1",
        "provider": "openai",
        "api_mode": "chat_completions",
        "api_key": os.environ["OPENAI_API_KEY"],
    }


class ConversationFiles:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, context_id):
        return self.directory / (hashlib.sha256(context_id.encode()).hexdigest() + ".json")

    def load(self, context_id):
        path = self.path(context_id)
        if not path.exists():
            return []
        messages = json.loads(path.read_text())
        if not isinstance(messages, list) or any(not isinstance(message, dict) for message in messages):
            raise ValueError("Invalid durable Hermes conversation")
        return messages

    def save(self, context_id, messages):
        if not isinstance(messages, list) or any(not isinstance(message, dict) for message in messages):
            raise ValueError("Hermes returned invalid conversation history")
        path = self.path(context_id)
        temporary = path.with_suffix(".tmp")
        with temporary.open("w") as stream:
            os.chmod(temporary, 0o600)
            json.dump(messages, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)


class HermesExecutor(AgentExecutor):
    def __init__(self, config, factory, directory="/data/hermes/conversations"):
        self.config = config
        self.factory = factory
        self.options = model_options(config)
        self.history = ConversationFiles(directory)
        self.active = None
        self.finished = asyncio.Event()
        self.finished.set()

    async def execute(self, context, events):
        if not context.message or any(not part.HasField("text") for part in context.message.parts):
            raise ValueError("Hermes currently accepts text messages only")
        prompt = "\n".join(part.text for part in context.message.parts)
        if not prompt.strip():
            raise ValueError("A nonempty text message is required")
        history = self.history.load(context.context_id)
        self.finished.clear()
        worker = None
        agent = None
        try:
            agent = self.factory(
                **self.options,
                session_id=context.context_id,
                enabled_toolsets=["terminal", "file"],
                max_iterations=30,
                quiet_mode=True,
                skip_background_review=True,
                cwd="/data/workspace",
            )
            self.active = agent
            await events.enqueue_event(
                pb.TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    status=pb.TaskStatus(state=pb.TASK_STATE_WORKING),
                )
            )
            worker = asyncio.create_task(
                asyncio.to_thread(
                    agent.run_conversation,
                    prompt,
                    system_message=self.config.get("instruction") or None,
                    conversation_history=history,
                    task_id=context.task_id,
                )
            )
            result = await asyncio.shield(worker)
            if result.get("interrupted"):
                raise asyncio.CancelledError()
            if result.get("error"):
                raise RuntimeError("Hermes execution failed; inspect runtime logs")
            answer = result.get("final_response")
            if not isinstance(answer, str) or not answer:
                raise RuntimeError("Hermes did not return a final response")
            self.history.save(context.context_id, result["messages"])
            await events.enqueue_event(
                pb.TaskArtifactUpdateEvent(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    last_chunk=True,
                    artifact=pb.Artifact(artifact_id=str(uuid4()), parts=[pb.Part(text=answer)]),
                )
            )
            await events.enqueue_event(
                pb.TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    status=pb.TaskStatus(state=pb.TASK_STATE_COMPLETED),
                )
            )
        except asyncio.CancelledError:
            if agent is not None:
                agent.interrupt()
            if worker is not None:
                await asyncio.shield(worker)
            raise
        finally:
            try:
                if agent is not None:
                    await asyncio.to_thread(agent.close)
            finally:
                self.active = None
                self.finished.set()

    async def cancel(self, context, events):
        if self.active is not None:
            self.active.interrupt()
        await self.finished.wait()
        await events.enqueue_event(
            pb.TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                status=pb.TaskStatus(state=pb.TASK_STATE_CANCELED),
            )
        )


async def serve():
    materialize_from_env("/config")
    config = json.loads(Path("/config/config.json").read_text())
    runtime = config["runtime"]
    card = ParseDict(json.loads(Path("/config/agent-card.json").read_text()), AgentCard())
    Path("/data/workspace").mkdir(parents=True, exist_ok=True)
    # Load Hermes before reporting readiness; this also verifies packaged dependencies.
    from run_agent import AIAgent

    executor = HermesExecutor(config, AIAgent)
    client = AsyncControllerClient(runtime["control_plane_url"], agent_name=runtime["name"])
    store = KAgentTaskStore(client)
    handler = KAgentRequestHandler(
        agent_executor=executor,
        task_store=store,
        agent_card=card,
        request_context_builder=KAgentRequestContextBuilder(store),
    )
    server = grpc.aio.server()
    a2a_pb2_grpc.add_A2AServiceServicer_to_server(
        GrpcHandler(handler, context_builder=KAgentGrpcServerCallContextBuilder()),
        server,
    )
    if not server.add_insecure_port("0.0.0.0:" + str(runtime.get("port") or 80)):
        raise RuntimeError("Cannot bind A2A listener")
    await server.start()

    async def readiness(reader, writer):
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            status = "200 OK" if line.startswith(b"GET /readyz ") else "404 Not Found"
            writer.write(f"HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    ready = await asyncio.start_server(readiness, "0.0.0.0", 8081)
    try:
        async with ready:
            await server.wait_for_termination()
    finally:
        await server.stop(grace=5)
        await client.close()


if __name__ == "__main__":
    asyncio.run(serve())
