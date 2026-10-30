"""Independent images are shared across a pool of models, each on its own quota."""

import threading
import time

import pytest
from gemini_shared.media import images as media


@pytest.fixture
def fake_generation(monkeypatch):
    """Record which model made each image instead of calling the service."""
    calls: list[tuple[str, str]] = []
    lock = threading.Lock()

    def generate(location, model, request, extra):
        time.sleep(0.02)
        with lock:
            calls.append((model, request.name))
        return media.GeneratedImage(request.name, b"png", "image/png", request.prompt)

    monkeypatch.setattr(media, "_generate_one", generate)
    monkeypatch.setattr(media, "_model_location", lambda: "global")
    monkeypatch.setattr(media, "DEFERRED_JOIN_SECONDS", 0.05)
    monkeypatch.setattr(media, "DEFERRED_POLL_SECONDS", 0.01)
    return calls


def _requests(count):
    return [media.ImageRequest(f"prompt {i}", f"image-{i}") for i in range(count)]


def test_every_model_in_the_pool_takes_a_share(fake_generation):
    images = media.generate_images(_requests(12), model="a", models=["a", "b", "c"])

    assert [image.name for image in images] == [f"image-{i}" for i in range(12)]
    assert {model for model, _ in fake_generation} == {"a", "b", "c"}


def test_a_deferred_model_waits_for_its_series_then_helps(fake_generation):
    media._series_models["pro"] += 1
    try:
        threading.Timer(0.15, lambda: media._series_models.update({"pro": -1})).start()
        media.generate_images(
            _requests(30), model="a", models=["a", "pro"], deferred_models=["pro"]
        )
    finally:
        media._series_models.pop("pro", None)

    pro_calls = [index for index, (model, _) in enumerate(fake_generation) if model == "pro"]
    assert pro_calls, "the deferred model never joined once its series ended"
    assert pro_calls[0] > 0, "the deferred model started before its series ended"


def test_a_failing_model_hands_its_work_to_the_others(monkeypatch, fake_generation):
    working = media._generate_one

    def flaky(location, model, request, extra):
        if model == "broken":
            raise RuntimeError("quota")
        return working(location, model, request, extra)

    monkeypatch.setattr(media, "_generate_one", flaky)
    images = media.generate_images(_requests(6), model="a", models=["a", "broken"])

    assert len(images) == 6
    assert {model for model, _ in fake_generation} == {"a"}


def test_the_batch_fails_when_every_model_has(monkeypatch, fake_generation):
    def broken(location, model, request, extra):
        raise RuntimeError("quota")

    monkeypatch.setattr(media, "_generate_one", broken)
    with pytest.raises(RuntimeError, match="quota"):
        media.generate_images(_requests(3), model="a", models=["a", "b"])
