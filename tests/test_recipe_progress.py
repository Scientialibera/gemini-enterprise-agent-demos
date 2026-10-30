"""No-cloud tests for the recipe agent's live progress lines."""

import asyncio
import time

from google.adk.agents import Agent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.adk.tools import ToolContext
from google.genai import types
from recipe_card_agent.progress import ProgressAgent, image_reporter

NAMES = ["garlic", "onion", "basil"]
TOOL = "generate_recipe_images"
PHOTOS = {"names": ["hero", "step-1"], "mode": "sequential_reference"}
RETRY = {"names": ["step-2"], "mode": "sequential_reference"}


async def generate_recipe_images(names: list[str], mode: str, tool_context: ToolContext) -> dict:
    """Stands in for the image tool: stores each image from a worker thread."""
    on_stored = image_reporter(tool_context.invocation_id, names)

    def work():
        for name in names:
            time.sleep(0.05)
            on_stored(name)

    await asyncio.to_thread(work)
    return {"status": "complete", "images": {name: f"{name}.png" for name in names}}


def run_card():
    requests = []

    class FakeModel(BaseLlm):
        async def generate_content_async(self, llm_request, stream=False):
            requests.append(llm_request)
            # Two image calls in one turn, as the card makes them, then one
            # more call, so the model reads the parallel pair back from history.
            if len(requests) == 1:
                parts = [
                    types.Part(function_call=types.FunctionCall(name=TOOL, args=args))
                    for args in ({"names": NAMES, "mode": "parallel"}, PHOTOS)
                ]
            elif len(requests) == 2:
                parts = [types.Part(function_call=types.FunctionCall(name=TOOL, args=RETRY))]
            else:
                parts = [types.Part(text="Card ready")]
            yield LlmResponse(content=types.Content(role="model", parts=parts))

    async def run():
        writer = Agent(
            name="writer",
            model=FakeModel(model="fake"),
            tools=[generate_recipe_images],
            disallow_transfer_to_parent=True,
        )
        runner = InMemoryRunner(
            agent=ProgressAgent(name="recipe_card_agent", sub_agents=[writer]), app_name="test"
        )
        session = await runner.session_service.create_session(app_name="test", user_id="test")
        events = [
            event
            async for event in runner.run_async(
                user_id="test",
                session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text="Chili")]),
            )
        ]
        await runner.close()
        return events

    return asyncio.run(run()), requests


def test_each_image_is_posted_while_the_tool_runs():
    events, _ = run_card()
    lines = [
        part.text.strip()
        for event in events
        for part in (event.content.parts if event.content else [])
        if part.text
    ]
    results = [i for i, event in enumerate(events) if event.get_function_responses()]
    first_result = events[results[0]].timestamp
    posted = {
        e.content.parts[0].text.strip(): e.timestamp
        for e in events
        if e.branch and "progress" in e.branch
    }
    assert lines[:2] == [
        "Photographing the ingredients: 3 images.",
        "Photographing the hero and steps: 2 images.",
    ]
    assert sorted(lines[2:7]) == sorted(
        [
            "- garlic ready (1 of 3)",
            "- onion ready (2 of 3)",
            "- basil ready (3 of 3)",
            "- hero ready (1 of 2)",
            "- step-1 ready (2 of 2)",
        ]
    )
    # Every line from the parallel pair is posted before either call returns.
    assert all(posted[line] <= first_result for line in lines[2:7])
    assert lines[-3:] == [
        "Photographing the hero and steps: 1 images.",
        "- step-2 ready (1 of 1)",
        "Card ready",
    ]


def test_model_history_never_contains_progress_lines():
    _, requests = run_card()
    for request in requests[1:]:
        contents = request.contents
        texts = [p.text for c in contents for p in c.parts if p.text]
        assert not any("ready (" in t or "Photographing" in t for t in texts)
        for i, content in enumerate(contents):
            calls = [p for p in content.parts if p.function_call]
            if calls:
                following = contents[i + 1].parts
                assert len([p for p in following if p.function_response]) == len(calls)


def test_reports_outside_a_run_are_dropped():
    image_reporter("no-such-invocation", NAMES)("garlic")
