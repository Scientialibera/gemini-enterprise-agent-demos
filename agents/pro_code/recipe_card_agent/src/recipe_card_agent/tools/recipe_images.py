"""Generate the card's photography in bounded batches."""

import asyncio

from gemini_shared.media.images import MODE_PARALLEL
from google.adk.tools import ToolContext
from recipe_cards import images


async def generate_recipe_images(
    recipe_slug: str,
    prompts: list[str],
    names: list[str],
    tool_context: ToolContext,
    mode: str = MODE_PARALLEL,
    run_id: str = "",
    use_reference_images: bool = True,
) -> dict[str, object]:
    # A synchronous tool blocks the event loop, so two image calls issued in one
    # turn would still run one after the other. Run in a worker thread instead,
    # so the ingredient batch and the photograph batch, which are paced on
    # separate model quotas, generate at the same time.
    return await asyncio.to_thread(
        images.generate_recipe_images,
        recipe_slug,
        prompts,
        names,
        tool_context,
        mode=mode,
        run_id=run_id,
        use_reference_images=use_reference_images,
    )


generate_recipe_images.__doc__ = images.generate_recipe_images.__doc__

__all__ = ["generate_recipe_images"]
