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
SKETCH = {"names": ["sketch"], "mode": "parallel"}
# The model's turns in a card: look for one, draw the sketch, two image calls at
# once, then one more, so the parallel pair is read back from history.
TURNS = [
    [("list_folders", {})],
    [(TOOL, SKETCH)],
    [(TOOL, {"names": NAMES, "mode": "parallel"}), (TOOL, PHOTOS)],
    [(TOOL, RETRY)],
]
PAIR = [
    "- garlic ready (1 of 3)",
    "- onion ready (2 of 3)",
    "- basil ready (3 of 3)",
    "- hero ready (1 of 2)",
    "- step-1 ready (2 of 2)",
]


def list_folders() -> dict:
    """Stands in for the card listing: no card exists yet."""
    return {"folder_count": 0, "folders": []}


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
            if len(requests) <= len(TURNS):
                parts = [
                    types.Part(function_call=types.FunctionCall(name=name, args=args))
                    for name, args in TURNS[len(requests) - 1]
                ]
            else:
                parts = [types.Part(text="Card ready")]
            yield LlmResponse(content=types.Content(role="model", parts=parts))

    async def run():
        writer = Agent(
            name="writer",
            model=FakeModel(model="fake"),
            tools=[list_folders, generate_recipe_images],
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


def test_each_step_and_image_is_posted_while_the_card_is_made():
    events, _ = run_card()
    lines = [
        part.text.strip()
        for event in events
        for part in (event.content.parts if event.content else [])
        if part.text
    ]
    assert lines[:4] == [
        "Writing the recipe.",
        "Drawing the sketch.",
        "- sketch ready (1 of 1)",
        "Writing the photograph prompts.",
    ]
    assert lines[4:6] == [
        "Photographing the ingredients: 3 images.",
        "Photographing the hero and steps: 2 images.",
    ]
    assert sorted(lines[6:11]) == sorted(PAIR)
    assert lines[11:] == [
        "Photographing the hero and steps: 1 images.",
        "- step-2 ready (1 of 1)",
        "Card ready",
    ]


def test_images_are_posted_before_their_call_returns():
    events, _ = run_card()
    pair_result = next(
        e.timestamp
        for e in events
        for r in e.get_function_responses()
        if "hero" in (r.response or {}).get("images", {})
    )
    posted = {
        e.content.parts[0].text.strip(): e.timestamp
        for e in events
        if e.branch and "progress" in e.branch
    }
    assert all(posted[line] <= pair_result for line in PAIR)


def test_model_history_never_contains_progress_lines():
    _, requests = run_card()
    for request in requests[1:]:
        contents = request.contents
        texts = [p.text for c in contents for p in c.parts if p.text]
        assert not any("ready (" in t or "Writing the" in t or "Photographing" in t for t in texts)
        for i, content in enumerate(contents):
            calls = [p for p in content.parts if p.function_call]
            if calls:
                following = contents[i + 1].parts
                assert len([p for p in following if p.function_response]) == len(calls)


def test_reports_outside_a_run_are_dropped():
    image_reporter("no-such-invocation", NAMES)("garlic")
