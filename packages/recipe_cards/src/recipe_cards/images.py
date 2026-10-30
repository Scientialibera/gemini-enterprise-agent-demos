"""Generate bounded image batches and register each asset in session state."""

from __future__ import annotations

import functools
from collections.abc import Callable

from gemini_shared.connectors.cloud_storage import upload_bytes
from gemini_shared.media import ImageRequest, generate_images
from gemini_shared.media.images import MODE_PARALLEL, MODE_SEQUENTIAL_REFERENCE, image_model_name
from gemini_shared.media.pacing import acquire_slot
from google.adk.tools import ToolContext

from .config import (
    OUTPUT_BUCKET,
    OUTPUT_BUCKET_ENV,
    PHOTO_IMAGE_MODEL,
    POOL_IMAGE_MODELS,
    PROJECT_ID,
    USE_CASE_PREFIX,
)
from .runs import get_run, new_run_id, safe_slug, save_run
from .schema import MAX_IMAGES_PER_BATCH, MAX_IMAGES_PER_RUN

IMAGE_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def _object_name(recipe_slug: str, run_id: str, image_name: str, extension: str = "png") -> str:
    """Group one run's images under their own prefix."""
    return (
        f"{USE_CASE_PREFIX}/{safe_slug(recipe_slug)}/{safe_slug(run_id, 'run')}"
        f"/images/{safe_slug(image_name, 'image')}.{extension}"
    )


def generate_recipe_images(
    recipe_slug: str,
    prompts: list[str],
    names: list[str],
    tool_context: ToolContext,
    mode: str = MODE_PARALLEL,
    run_id: str = "",
    use_reference_images: bool = True,
    on_stored: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Generate recipe images and return paths relative to the card store.

    Use `parallel` for images that do not depend on each other, such as the
    ingredient cutouts. Use `sequential_reference` for a series that must look
    like one continuous shoot, such as the numbered cooking steps: each image
    is generated with the previous ones as references, so the pot, surface and
    lighting stay the same without you passing images yourself.

    Write the full art direction into every prompt. Nothing is added for you.
    Generate the sketch first; it returns the run_id. Then request the
    ingredients and the hero-and-steps series in the same turn, both with that
    run_id: they use separate model quotas and run at the same time.
    Use retrieve to check the stored files before rendering.
    A partial result preserves successful uploads and supplies remaining_names.
    Retrieve the run folder, then retry only missing names with the same run_id.

    Args:
        recipe_slug: Identifier for the recipe, used as the storage prefix.
        prompts: One prompt per image, in the order they should be produced.
        names: One short name per image, positionally matching `prompts`.
            Used as the stored file name, for example `hero` or `step-1`.
        use_reference_images: In sequential mode, each image is generated with
            the preceding ones as references. For the sketch set False with
            mode="parallel"; no reference images will be sent. Each batch
            accepts at most 24 images and each run at most 48.
        mode: `parallel` or `sequential_reference`.
        run_id: Pass the `run_id` returned by your first call so every image
            for one card is stored together. Omit it on the first call and one
            is created for you.
    """
    if not OUTPUT_BUCKET:
        raise RuntimeError(
            f"{OUTPUT_BUCKET_ENV} is not set, so there is nowhere to publish the images."
        )
    if not use_reference_images and mode != MODE_PARALLEL:
        raise ValueError('No-reference generation requires mode="parallel".')
    if len(prompts) != len(names):
        raise ValueError(
            f"Received {len(prompts)} prompts and {len(names)} names. "
            "Supply exactly one name per prompt."
        )
    if not prompts:
        raise ValueError("No prompts were supplied.")
    if len(prompts) > MAX_IMAGES_PER_BATCH:
        raise ValueError(f"At most {MAX_IMAGES_PER_BATCH} images may be generated per batch.")
    if any(not p.strip() or len(p) > 4000 for p in prompts):
        raise ValueError("Each image prompt must contain 1-4000 characters.")
    normalized_names = [safe_slug(name, "") for name in names]
    if not all(normalized_names) or len(set(normalized_names)) != len(names):
        raise ValueError("Image names must be nonempty and unique after normalization.")
    if mode not in (MODE_PARALLEL, MODE_SEQUENTIAL_REFERENCE):
        raise ValueError(
            f"Unknown mode '{mode}'. Use '{MODE_PARALLEL}' for independent images "
            f"or '{MODE_SEQUENTIAL_REFERENCE}' for a consistent series."
        )

    slug = safe_slug(recipe_slug)
    run = get_run(tool_context, run_id) if run_id else {"slug": slug, "images": {}}
    if run["slug"] != slug:
        raise ValueError("The run belongs to a different recipe.")
    existing = dict(run["images"])
    if set(normalized_names) & existing.keys():
        raise ValueError("An image with that name already exists in this run; use a new name.")
    if len(existing) + len(names) > MAX_IMAGES_PER_RUN:
        raise ValueError(f"At most {MAX_IMAGES_PER_RUN} images may be generated per recipe run.")
    run_id = run_id or new_run_id()
    save_run(tool_context, run_id, run)
    # No house style plates are sent. They are photographs of finished cards,
    # and every model shown them has at some point drawn a card instead of its
    # subject: a hero came back as a spaghetti step-card, ingredient cutouts as
    # miniature cards, and step photographs late in a Pro series as whole
    # pages. The prompts carry the house look in words, and a series is held
    # together by its own earlier photographs, which the shared helper passes.
    uris = {}

    def checkpoint(image):
        if image.name in uris:
            return
        if image.mime_type not in IMAGE_EXTENSIONS:
            raise ValueError("Unsupported generated image type.")
        object_name = _object_name(slug, run_id, image.name, IMAGE_EXTENSIONS[image.mime_type])
        upload_bytes(
            PROJECT_ID,
            OUTPUT_BUCKET,
            object_name,
            image.data,
            image.mime_type,
            create_only=True,
        )
        # Relative to the card store, which is what a recipe's image fields
        # take. The model never handles a bucket name or an absolute URI.
        relative = object_name.removeprefix(f"{USE_CASE_PREFIX}/")
        uris[image.name] = relative
        existing[safe_slug(image.name)] = relative
        save_run(tool_context, run_id, {**run, "images": existing})
        if on_stored:
            on_stored(image.name)

    failure = None
    model = image_model_name()
    # The hero and step photographs are what a reader looks at, and where a
    # faster model draws physically impossible scenes (a ladle floating over
    # the pot). They are few, so they can afford the slower, better model.
    if mode == MODE_SEQUENTIAL_REFERENCE and PHOTO_IMAGE_MODEL:
        model = PHOTO_IMAGE_MODEL
    # Independent images are shared across every available model, each paced
    # to its own quota. The photo model is deferred: it starts on the series it
    # was chosen for and helps with whatever cutouts are left once that ends.
    pool = (model, *POOL_IMAGE_MODELS, *((PHOTO_IMAGE_MODEL,) if PHOTO_IMAGE_MODEL else ()))
    try:
        images = generate_images(
            [
                ImageRequest(
                    prompt=prompt,
                    name=name,
                    request_slot=functools.partial(acquire_slot, PROJECT_ID, OUTPUT_BUCKET),
                )
                for prompt, name in zip(prompts, names, strict=True)
            ],
            mode=mode,
            on_image=checkpoint,
            model=model,
            models=pool,
            deferred_models=(PHOTO_IMAGE_MODEL,) if PHOTO_IMAGE_MODEL else (),
        )
        for image in images:
            checkpoint(image)
    except Exception as error:
        failure = type(error).__name__
    return {
        "status": "partial" if failure else "complete",
        "error_type": failure,
        "remaining_names": [name for name in names if name not in uris],
        "next_action": "Use retrieve, then retry only missing images with this run_id."
        if failure
        else "Continue with the next batch.",
        "bucket": OUTPUT_BUCKET,
        "mode": mode,
        # Pass this back on the next call and to render_recipe_card, so one
        # card's images and deck stay together.
        "run_id": run_id,
        "image_count": len(uris),
        "images": uris,
    }
