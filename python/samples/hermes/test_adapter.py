import asyncio
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from a2a.types import a2a_pb2 as pb
from adapter import ConversationFiles, HermesExecutor, model_options


class Queue:
    def __init__(self):
        self.events = []
        self.started = asyncio.Event()

    async def enqueue_event(self, event):
        self.events.append(event)
        self.started.set()


class FakeAgent:
    def __init__(self, **kwargs):
        self.options = kwargs
        self.stopped = threading.Event()
        self.closed = False

    def run_conversation(self, prompt, **kwargs):
        history = kwargs["conversation_history"]
        if prompt == "wait":
            self.stopped.wait(5)
            return {"interrupted": True}
        if prompt == "fail":
            raise RuntimeError("model unavailable")
        answer = str(len(history))
        return {
            "final_response": answer,
            "messages": history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": answer}],
        }

    def interrupt(self):
        self.stopped.set()

    def close(self):
        self.closed = True


def request(prompt):
    return SimpleNamespace(
        context_id="session-one",
        task_id="task-one",
        message=pb.Message(parts=[pb.Part(text=prompt)]),
    )


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(os.environ, {"OPENAI_API_KEY": "placeholder"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.config = {"model": {"type": "openai", "model": "test-model"}}
        self.agents = []

        def factory(**kwargs):
            agent = FakeAgent(**kwargs)
            self.agents.append(agent)
            return agent

        self.factory = factory
        self.executor = HermesExecutor(self.config, factory, self.directory.name)

    async def test_history_survives_executor_replacement(self):
        await self.executor.execute(request("first"), Queue())
        replacement = HermesExecutor(self.config, self.factory, self.directory.name)
        queue = Queue()
        await replacement.execute(request("second"), queue)
        artifact = next(event for event in queue.events if isinstance(event, pb.TaskArtifactUpdateEvent))
        self.assertEqual(artifact.artifact.parts[0].text, "2")
        self.assertEqual(queue.events[-1].status.state, pb.TASK_STATE_COMPLETED)
        self.assertTrue(all(agent.closed for agent in self.agents))

    async def test_failure_preserves_previous_history(self):
        await self.executor.execute(request("first"), Queue())
        with self.assertRaisesRegex(RuntimeError, "model unavailable"):
            await self.executor.execute(request("fail"), Queue())
        self.assertEqual(len(self.executor.history.load("session-one")), 2)
        self.assertTrue(self.agents[-1].closed)
        self.assertTrue(self.executor.finished.is_set())

    async def test_cancel_waits_for_native_cleanup(self):
        execution_events = Queue()
        run = asyncio.create_task(self.executor.execute(request("wait"), execution_events))
        await execution_events.started.wait()
        queue = Queue()
        await asyncio.wait_for(self.executor.cancel(request("wait"), queue), 2)
        with self.assertRaises(asyncio.CancelledError):
            await run
        self.assertTrue(self.agents[-1].closed)
        self.assertEqual(queue.events[-1].status.state, pb.TASK_STATE_CANCELED)

    async def test_transport_cancellation_stops_native_work(self):
        execution_events = Queue()
        run = asyncio.create_task(self.executor.execute(request("wait"), execution_events))
        await execution_events.started.wait()
        run.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(run, 2)
        self.assertTrue(self.agents[-1].closed)
        self.assertTrue(self.agents[-1].stopped.is_set())

    def test_rejects_corrupt_durable_history(self):
        store = ConversationFiles(self.directory.name)
        store.path("session-one").write_text(json.dumps({"unexpected": True}))
        with self.assertRaisesRegex(ValueError, "Invalid durable"):
            store.load("session-one")

    def test_context_id_cannot_escape_directory(self):
        store = ConversationFiles(self.directory.name)
        self.assertEqual(store.path("../../elsewhere").parent, Path(self.directory.name))

    def test_rejects_unsupported_model_protocol(self):
        self.config["model"]["api_format"] = "responses"
        with self.assertRaisesRegex(ValueError, "chatCompletions"):
            model_options(self.config)


if __name__ == "__main__":
    unittest.main()
