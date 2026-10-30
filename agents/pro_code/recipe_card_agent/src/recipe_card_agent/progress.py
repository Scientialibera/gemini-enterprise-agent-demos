"""Post the card's progress to the chat while the long tool calls run.

A card spends most of its ten minutes inside two image calls, and the chat shows
nothing while a tool runs. Outside live mode a tool cannot post a message
itself, so the image tool reports each stored image through a callback
registered for its invocation, and ProgressAgent, the root agent, posts each
report as a message while the tool is still working. It also posts a line as
each long step starts, the way the Growth workflow does between its stages.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncGenerator, Callable

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

_reporters: dict[str, Callable[[str], None]] = {}
_lock = threading.Lock()

STEP_LINES = {
    "check_recipe": "Checking the recipe against the card's limits.",
    "render_recipe_card": "Rendering the deck and publishing it.",
}


def report(invocation_id: str, text: str) -> None:
    """Post a line to the chat of the run with this invocation; safe from any thread."""
    with _lock:
        post = _reporters.get(invocation_id)
    if post:
        post(text)


def image_reporter(invocation_id: str, names: list[str]) -> Callable[[str], None]:
    """A callback for one image batch that posts each stored image with a count."""
    stored: list[str] = []
    lock = threading.Lock()

    def on_stored(name: str) -> None:
        with lock:
            stored.append(name)
            done = len(stored)
        report(invocation_id, f"- {name} ready ({done} of {len(names)})")

    return on_stored


def _start_line(call: types.FunctionCall) -> str | None:
    """The line announcing a tool call, or None for the quick ones."""
    if call.name != "generate_recipe_images":
        return STEP_LINES.get(call.name)
    names = (call.args or {}).get("names") or []
    if names == ["sketch"]:
        return "Drawing the sketch."
    if (call.args or {}).get("mode") == "sequential_reference":
        return f"Photographing the hero and steps: {len(names)} images."
    return f"Photographing the ingredients: {len(names)} images."


class ProgressAgent(BaseAgent):
    """Runs its one sub-agent and posts progress lines alongside its events."""

    def _message(self, ctx: InvocationContext, text: str) -> Event:
        # Gemini Enterprise joins a run's messages into one reply. An image line
        # ends with one newline so a batch reads as a list; a step line is its
        # own paragraph.
        text = text + "\n" if text.startswith("- ") else f"\n{text}\n\n"
        return Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            # A branch beside the worker's, so the chat shows the line but the
            # model never reads it back. In its history a line would sit between
            # the image calls and their results, and Gemini rejects a request
            # whose parallel calls are not followed directly by their results.
            branch=f"{self.name}.progress",
            content=types.Content(role="model", parts=[types.Part(text=text)]),
        )

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        worker = self.sub_agents[0]
        worker_ctx = ctx.model_copy(update={"branch": worker.name})
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, object, asyncio.Future | None]] = asyncio.Queue()

        def post(text: str) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, ("line", text, None))

        async def relay() -> None:
            try:
                async for event in worker.run_async(worker_ctx):
                    stored = loop.create_future()
                    await queue.put(("event", event, stored))
                    # The runner stores an event before asking for the next, and
                    # the worker reads the session back on its next model call,
                    # so it waits until its event has been passed on.
                    await stored
            finally:
                await queue.put(("end", None, None))

        with _lock:
            _reporters[ctx.invocation_id] = post
        task = asyncio.create_task(relay())
        try:
            while True:
                kind, item, stored = await queue.get()
                if kind == "end":
                    break
                if kind == "line":
                    yield self._message(ctx, item)
                    continue
                for call in item.get_function_calls():
                    line = _start_line(call)
                    if line:
                        yield self._message(ctx, line)
                yield item
                stored.set_result(None)
            await task
        finally:
            with _lock:
                _reporters.pop(ctx.invocation_id, None)
            task.cancel()
