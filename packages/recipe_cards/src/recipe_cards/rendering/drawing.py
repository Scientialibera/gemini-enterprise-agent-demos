"""Drawing primitives and typography for recipe cards."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls, qn
from pptx.util import Inches, Pt

from .assets import CURRENT_ASSETS
from .assets import resolve as _resolve
from .theme import (
    BODY_FONT,
    BOLD_WIDTH_FACTOR,
    CHAR_WIDTH_RATIO,
    HEAD_CHAR_WIDTH_RATIO,
    HEAD_FONT,
    LINE_HEIGHT_RATIO,
    POINTS_PER_INCH,
    C,
)


def rgb(hex_color: str) -> RGBColor:
    h = hex_color.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def clean(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    return str(value)


def limit_text(value: Any, n: int) -> str:
    """Trim to a length, breaking on a word so the tail stays readable."""
    s = clean(value)
    if len(s) <= n:
        return s
    cut = s[: max(0, n - 1)]
    # Prefer the last space, unless that throws away most of the text.
    space = cut.rfind(" ")
    if space > n * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:") + "…"


def servings_label(value: Any) -> str:
    """Return "4 SERVINGS" whether the value is "4" or "4 servings".

    A model writes the unit as often as it omits it, and the template supplies
    one of its own, so the word is stripped before it is added back.
    """
    text = clean(value, "4").strip()
    lowered = text.lower()
    for suffix in ("servings", "serving", "portions", "portion"):
        if lowered.endswith(suffix):
            text = text[: -len(suffix)].strip().strip("-")
            break
    return f"{text or '4'} SERVINGS"


def exists(path: Any) -> bool:
    resolved = _resolve(path)
    return bool(resolved) and os.path.exists(resolved)


def chunks(seq: list[Any], size: int) -> Iterable[list[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


# -----------------------------------------------------------------------------
# LOW-LEVEL DRAWING HELPERS
# -----------------------------------------------------------------------------


# Autofit is a hint the renderer may honour: PowerPoint applies it, LibreOffice
# and PDF export do not. Text is therefore measured here and the size chosen
# before it is written, so a long title or a wordy step looks the same wherever
# the deck is opened.

# Mean advance width of one character as a fraction of font size, measured over
# running sentence text in each face (0.434 body, 0.394 headings) and rounded up
# slightly so an unusually wide line still fits.


def wrapped_line_count(text: str, width_in: float, font_size: float, ratio: float) -> int:
    """Lines this text needs at a size, wrapping on words like the renderer."""
    char_w = (font_size * ratio) / POINTS_PER_INCH
    if char_w <= 0:
        return 1
    per_line = max(1, int(width_in / char_w))
    lines = 0
    for paragraph in (text or " ").splitlines() or [" "]:
        words, current = paragraph.split(), 0
        if not words:
            lines += 1
            continue
        line_len = 0
        for word in words:
            need = len(word) if line_len == 0 else line_len + 1 + len(word)
            if need <= per_line:
                line_len = need
            else:
                current += 1
                line_len = len(word)
        lines += current + 1
    return max(1, lines)


def fit_to_box(
    text: Any,
    width_in: float,
    height_in: float,
    font_size: float,
    *,
    head: bool = False,
    bold: bool = False,
) -> str:
    """Trim text to what the box holds at a fixed size.

    Type sizes are part of the design, so they do not change from card to card.
    When a value is too long for its panel the value is shortened, which keeps
    every card's hierarchy identical and legible.
    """
    body = clean(text)
    if not body:
        return body

    ratio = HEAD_CHAR_WIDTH_RATIO if head else CHAR_WIDTH_RATIO
    # Bold body type runs wider than the regular face these ratios measured:
    # a subtitle counted as two lines set as three and ran into the pill.
    if bold and not head:
        ratio *= BOLD_WIDTH_FACTOR
    max_lines = max(1, int((height_in * POINTS_PER_INCH) / (font_size * LINE_HEIGHT_RATIO)))
    if wrapped_line_count(body, width_in, font_size, ratio) <= max_lines:
        return body

    char_w = (font_size * ratio) / POINTS_PER_INCH
    per_line = max(1, int(width_in / char_w))
    # One ellipsis replaces the tail, so the sentence ends deliberately rather
    # than colliding with the edge of the panel.
    budget = max(1, per_line * max_lines - 1)
    return limit_text(body, budget)


def add_box(slide, x, y, w, h, fill, line=None, radius=False):
    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE
    shp = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
    shp.fill.solid()
    shp.fill.fore_color.rgb = rgb(fill)
    shp.line.color.rgb = rgb(line or fill)
    shp.line.width = Pt(0.9 if line else 0.1)
    # Reduce the exaggerated corner rounding of PowerPoint's rounded rectangle.
    if radius and hasattr(shp, "adjustments") and len(shp.adjustments):
        try:
            shp.adjustments[0] = 0.08
        except Exception:
            pass
    return shp


def gradient_fill(shape, top: str, bottom: str) -> None:
    """Fill a shape with a vertical gradient, lighter at the top.

    A flat mid-blue behind white type read as washed out; a gentle fall to a
    deeper tone gives the header depth and lifts the title's contrast where
    it sits, without changing the brand colour.
    """
    shape.fill.gradient()
    shape.fill.gradient_angle = 90
    stops = shape.fill.gradient_stops
    stops[0].position, stops[1].position = 0.0, 1.0
    stops[0].color.rgb = rgb(top)
    stops[1].color.rgb = rgb(bottom)
    shape.line.fill.background()


def add_soft_shadow(shape, *, blur=0.09, distance=0.025, alpha=20) -> None:
    """Give a panel or photograph a soft drop shadow so it sits on the page.

    Set explicitly rather than inherited: the theme default is a hard offset
    shadow that renders differently in each viewer.
    """
    sp_pr = shape._element.spPr
    for existing in sp_pr.findall(qn("a:effectLst")):
        sp_pr.remove(existing)
    sp_pr.append(
        parse_xml(
            f'<a:effectLst {nsdecls("a")}><a:outerShdw blurRad="{int(Inches(blur))}" '
            f'dist="{int(Inches(distance))}" dir="5400000" algn="t" rotWithShape="0">'
            f'<a:srgbClr val="1D2530"><a:alpha val="{alpha * 1000}"/></a:srgbClr>'
            "</a:outerShdw></a:effectLst>"
        )
    )


def no_shadow(shape) -> None:
    """Drop the theme's default shadow from a flat element such as a rule."""
    shape.shadow.inherit = False


def round_picture(picture, ratio=0.05) -> None:
    """Round a photograph's corners, as the reference cards set them.

    ``ratio`` is the corner radius as a share of the shorter side; PowerPoint's
    own default of a sixth reads as a pill rather than a print photograph.
    """
    geometry = picture._element.spPr.find(qn("a:prstGeom"))
    if geometry is None:
        return
    geometry.set("prst", "roundRect")
    for existing in geometry.findall(qn("a:avLst")):
        geometry.remove(existing)
    geometry.append(
        parse_xml(
            f'<a:avLst {nsdecls("a")}><a:gd name="adj" fmla="val {int(ratio * 100000)}"/></a:avLst>'
        )
    )


def add_rule(slide, x, y, w, color=None, width=1.0):
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Pt(width))
    line.fill.solid()
    line.fill.fore_color.rgb = rgb(color or C["line"])
    line.line.fill.background()
    no_shadow(line)
    return line


def add_vrule(slide, x, y, h, color=None, width=1.0):
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Pt(width), Inches(h))
    line.fill.solid()
    line.fill.fore_color.rgb = rgb(color or C["line"])
    line.line.fill.background()
    no_shadow(line)
    return line


def add_text(
    slide,
    text,
    x,
    y,
    w,
    h,
    *,
    font_size=12,
    font_face=BODY_FONT,
    color=None,
    bold=False,
    italic=False,
    align="left",
    valign="middle",
    margin=0.0,
    fit=True,
    line_spacing=None,
):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.clear()
    tf.margin_left = Inches(margin)
    tf.margin_right = Inches(margin)
    tf.margin_top = Inches(margin)
    tf.margin_bottom = Inches(margin)
    tf.word_wrap = True
    tf.vertical_anchor = {
        "top": MSO_ANCHOR.TOP,
        "middle": MSO_ANCHOR.MIDDLE,
        "bottom": MSO_ANCHOR.BOTTOM,
    }.get(valign, MSO_ANCHOR.MIDDLE)
    if fit:
        tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        # Type sizes are fixed so every card reads the same. Text that would
        # overflow is trimmed to what the box holds at this size rather than
        # shrunk, which would make one card's body copy smaller than another's.
        text = fit_to_box(
            text,
            max(0.1, w - 2 * margin),
            max(0.1, h),
            font_size,
            head=font_face == HEAD_FONT,
            bold=bold,
        )

    p = tf.paragraphs[0]
    p.alignment = {
        "left": PP_ALIGN.LEFT,
        "center": PP_ALIGN.CENTER,
        "right": PP_ALIGN.RIGHT,
    }.get(align, PP_ALIGN.LEFT)
    if line_spacing is not None:
        p.line_spacing = line_spacing

    run = p.add_run()
    run.text = clean(text)
    f = run.font
    f.name = font_face
    f.size = Pt(font_size)
    f.bold = bold
    f.italic = italic
    f.color.rgb = rgb(color or C["ink"])
    return box


BULLET_INDENT = 0.16


def bullet_list_height(items: list[str], width: float, font_size: float) -> float:
    """Height a bulleted list needs, counting the lines each item wraps to.

    Measured a little narrower than the text column, because PowerPoint breaks
    lines slightly earlier than the mean character width predicts.
    """
    text_w = max(0.3, width - BULLET_INDENT - 0.12)
    lines = sum(wrapped_line_count(item, text_w, font_size, CHAR_WIDTH_RATIO) for item in items)
    return lines * font_size * LINE_HEIGHT_RATIO / POINTS_PER_INCH


def add_bullet_list(slide, items, x, y, w, h, *, font_size, color=None):
    """One paragraph per item with a real bullet and a hanging indent.

    A typed "•" would leave a wrapped item's second line under the bullet;
    PowerPoint's own bullets keep it aligned with the text above.
    """
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    indent = int(Inches(BULLET_INDENT))
    for index, item in enumerate(items):
        paragraph = tf.paragraphs[0] if index == 0 else tf.add_paragraph()
        properties = paragraph._p.get_or_add_pPr()
        properties.set("marL", str(indent))
        properties.set("indent", str(-indent))
        properties.append(parse_xml(f'<a:buFont {nsdecls("a")} typeface="Arial"/>'))
        properties.append(parse_xml(f'<a:buChar {nsdecls("a")} char="•"/>'))
        run = paragraph.add_run()
        run.text = item
        run.font.name = BODY_FONT
        run.font.size = Pt(font_size)
        run.font.color.rgb = rgb(color or C["ink"])
    return box


CHECKLIST_INDENT = 0.26


def _checkbox_image() -> str:
    """A navy-outlined checkbox drawn once, for use as a picture bullet."""
    path = Path(tempfile.gettempdir()) / "recipe-checkbox-v1.png"
    if not path.exists():
        size, stroke = 96, 7
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(image).rounded_rectangle(
            (stroke // 2, stroke // 2, size - 1 - stroke // 2, size - 1 - stroke // 2),
            radius=18,
            fill=(255, 255, 255, 255),
            outline=tuple(int(C["dark_blue"].lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)),
            width=stroke,
        )
        image.save(path)
    return str(path)


def add_checklist(slide, items, x, y, w, h, *, font_size, space_after, color=None):
    """One text box of instructions, each with a checkbox as its bullet.

    A separate box per instruction had to be placed at a measured height, and
    every line the estimate miscounted showed as an uneven gap between two
    instructions. As paragraphs of one box, PowerPoint sets the spacing itself,
    and the checkbox stays on the first line with wrapped lines hanging under
    the text rather than under the box.
    """
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    _, r_id = slide.part.get_or_add_image_part(_checkbox_image())
    indent = int(Inches(CHECKLIST_INDENT))
    for index, item in enumerate(items):
        paragraph = tf.paragraphs[0] if index == 0 else tf.add_paragraph()
        properties = paragraph._p.get_or_add_pPr()
        properties.set("marL", str(indent))
        properties.set("indent", str(-indent))
        for markup in (
            f'<a:spcAft {nsdecls("a")}><a:spcPts val="{int(space_after * 100)}"/></a:spcAft>',
            f'<a:buSzPct {nsdecls("a")} val="90000"/>',
            f'<a:buBlip {nsdecls("a", "r")}><a:blip r:embed="{r_id}"/></a:buBlip>',
        ):
            properties.append(parse_xml(markup))
        run = paragraph.add_run()
        run.text = item
        run.font.name = BODY_FONT
        run.font.size = Pt(font_size)
        run.font.color.rgb = rgb(color or C["ink"])
    return box


def add_checkbox(slide, x, y, size=0.12):
    shp = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(size), Inches(size)
    )
    shp.adjustments[0] = 0.22
    shp.fill.solid()
    shp.fill.fore_color.rgb = rgb(C["white"])
    shp.line.color.rgb = rgb(C["dark_blue"])
    shp.line.width = Pt(0.9)
    no_shadow(shp)
    return shp


def _image_size(path: str) -> tuple[int, int]:
    with Image.open(_resolve(path)) as im:
        return im.size


def add_picture_crop(slide, path: str, x, y, w, h):
    """Add image cropped to fill a target box without distorting aspect ratio."""
    if not exists(path):
        return None
    iw, ih = _image_size(path)
    src_aspect = iw / ih
    dst_aspect = w / h
    pic = slide.shapes.add_picture(
        _resolve(path), Inches(x), Inches(y), width=Inches(w), height=Inches(h)
    )
    if src_aspect > dst_aspect:
        # Image is wider than target: crop left/right.
        shown_ratio = dst_aspect / src_aspect
        crop = (1.0 - shown_ratio) / 2.0
        pic.crop_left = crop
        pic.crop_right = crop
    elif src_aspect < dst_aspect:
        # Image is taller than target: crop top/bottom.
        shown_ratio = src_aspect / dst_aspect
        crop = (1.0 - shown_ratio) / 2.0
        pic.crop_top = crop
        pic.crop_bottom = crop
    return pic


# A line drawing arrives as ink on a solid white field, and dropped onto the
# cream variations panel that field reads as a white patch stuck to the page.
# Keying the white out lets the ink sit directly on the panel, the way the
# reference cards set their sketches.
# Light neutrals are background, not ink. The cutoff is well below white
# because a model asked for a transparent background sometimes draws the
# checkerboard that represents one, in greys around 220.
_INK_WHITE_CUTOFF = 205
_INK_SOFT_EDGE = 45
# A pixel is only background if it is also unsaturated: this keeps pale
# ink from being erased along with the checkerboard.
_INK_MAX_SATURATION = 26

# A product photograph's backdrop is keyed by flooding in from the corners, so
# these bound what counts as backdrop rather than what counts as white. The
# floor stops a dark-cornered photograph being flooded at all; the tolerance
# follows the gentle gradient of studio lighting without crossing the subject.
_CUTOUT_WHITE_FLOOR = 225
_CUTOUT_TOLERANCE = 18
_CUTOUT_SOFT_EDGE = 1.2


def _transparent_ink(path: str, directory: str) -> str:
    """Return a copy of a line drawing with its white background removed.

    Pixels at or above the cutoff become fully transparent and the band just
    below it fades, so the strokes keep a soft edge instead of an aliased one.
    """
    resolved = _resolve(path)
    assets = CURRENT_ASSETS.get()
    if assets is None:
        return ""
    if not resolved or not os.path.exists(resolved):
        return resolved
    if resolved in assets.transparent:
        return assets.transparent[resolved]

    try:
        with Image.open(resolved) as source:
            image = source.convert("RGBA")
        red, green, blue, original_alpha = image.split()
        low = ImageChops.darker(ImageChops.darker(red, green), blue)
        high = ImageChops.lighter(ImageChops.lighter(red, green), blue)
        neutral = ImageChops.subtract(high, low).point(
            lambda value: 255 if value <= _INK_MAX_SATURATION else 0
        )
        fade = low.point(
            lambda value: max(0, min(255, int(255 * (_INK_WHITE_CUTOFF - value) / _INK_SOFT_EDGE)))
        )
        alpha = Image.composite(fade, Image.new("L", image.size, 255), neutral)
        image.putalpha(ImageChops.multiply(alpha, original_alpha))
        target = Path(directory) / f"ink-{hashlib.sha256(resolved.encode()).hexdigest()[:12]}.png"
        image.save(target)
        assets.transparent[resolved] = str(target)
        assets.local_paths.add(str(target))
        return str(target)
    except Exception:
        # A drawing that cannot be keyed is still better placed than dropped.
        return resolved


def _transparent_cutout(path: str, directory: str) -> str:
    """Return a copy of a product photograph with its backdrop removed.

    A photograph cannot be keyed the way a line drawing is. Thresholding every
    near-white pixel would hollow out the subject itself: a salsa in a white
    ramekin reads as 84% near-white, and most of that is the bowl. So the
    backdrop is found by flooding inwards from the four corners and only
    pixels reachable from an edge are cleared, which leaves an enclosed white
    subject intact.
    """
    resolved = _resolve(path)
    assets = CURRENT_ASSETS.get()
    if assets is None:
        return ""
    if not resolved or not os.path.exists(resolved):
        return resolved
    if resolved in assets.transparent:
        return assets.transparent[resolved]

    try:
        with Image.open(resolved) as source:
            image = source.convert("RGBA")
        width, height = image.size
        # Flooding a scratch copy marks the backdrop; the image is untouched.
        scratch = image.convert("L")
        for seed in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
            if scratch.getpixel(seed) >= _CUTOUT_WHITE_FLOOR:
                ImageDraw.floodfill(scratch, seed, 0, thresh=_CUTOUT_TOLERANCE)
        backdrop = scratch.point(lambda value: 0 if value == 0 else 255)
        # Feather the boundary so the subject keeps a soft edge rather than a
        # hard stair-stepped one against the panel.
        alpha = backdrop.filter(ImageFilter.GaussianBlur(_CUTOUT_SOFT_EDGE))
        image.putalpha(ImageChops.multiply(alpha, image.split()[3]))
        target = Path(directory) / f"cut-{hashlib.sha256(resolved.encode()).hexdigest()[:12]}.png"
        image.save(target)
        assets.transparent[resolved] = str(target)
        assets.local_paths.add(str(target))
        return str(target)
    except Exception:
        # An unkeyable photograph is still better placed than dropped.
        return resolved


def add_cutout_image(slide, path, x, y, w, h, *, placeholder="", quiet=True):
    """Place a product photograph with its backdrop keyed out."""
    assets = CURRENT_ASSETS.get()
    if exists(path) and assets is not None:
        keyed = _transparent_cutout(path, assets.directory)
        if keyed and os.path.exists(keyed):
            try:
                return _add_picture_trimmed(slide, keyed, x, y, w, h)
            except Exception:
                pass
    return add_image(slide, path, x, y, w, h, crop=False, placeholder=placeholder, quiet=quiet)


_TRIM_ALPHA_FLOOR = 16
_TRIM_MARGIN = 0.04


def _add_picture_trimmed(slide, path: str, x, y, w, h):
    """Place a keyed cutout scaled to its subject rather than to its canvas.

    A product shot centres a small subject on a large white field, so once the
    field is keyed out the ingredient fills a fraction of its slot and reads as
    a speck. The picture is cropped to the visible subject, with a little air,
    and that region is what is fitted to the slot. The file is untouched.
    """
    with Image.open(path) as image:
        width, height = image.size
        mask = (
            image.convert("RGBA")
            .split()[3]
            .point(lambda value: 255 if value > _TRIM_ALPHA_FLOOR else 0)
        )
        box = mask.getbbox()
    if not box:
        return add_picture_contain(slide, path, x, y, w, h)
    pad_x, pad_y = width * _TRIM_MARGIN, height * _TRIM_MARGIN
    left, top = max(0, box[0] - pad_x), max(0, box[1] - pad_y)
    right, bottom = min(width, box[2] + pad_x), min(height, box[3] + pad_y)
    region_aspect = (right - left) / (bottom - top)
    if region_aspect >= w / h:
        rw, rh = w, w / region_aspect
    else:
        rw, rh = h * region_aspect, h
    picture = slide.shapes.add_picture(
        path,
        Inches(x + (w - rw) / 2),
        Inches(y + (h - rh) / 2),
        width=Inches(rw),
        height=Inches(rh),
    )
    picture.crop_left = left / width
    picture.crop_right = 1 - right / width
    picture.crop_top = top / height
    picture.crop_bottom = 1 - bottom / height
    return picture


def add_ink_image(slide, path, x, y, w, h, *, placeholder="SKETCH"):
    """Place a line drawing with its white background keyed out."""
    assets = CURRENT_ASSETS.get()
    if exists(path) and assets is not None:
        keyed = _transparent_ink(path, assets.directory)
        if keyed and os.path.exists(keyed):
            try:
                return add_picture_contain(slide, keyed, x, y, w, h)
            except Exception:
                pass
    return add_image(slide, path, x, y, w, h, crop=False, placeholder=placeholder, quiet=True)


def add_picture_contain(slide, path: str, x, y, w, h):
    """Add image fully contained in target box, preserving aspect ratio."""
    if not exists(path):
        return None
    iw, ih = _image_size(path)
    src_aspect = iw / ih
    dst_aspect = w / h
    if src_aspect >= dst_aspect:
        rw = w
        rh = w / src_aspect
        rx = x
        ry = y + (h - rh) / 2
    else:
        rh = h
        rw = h * src_aspect
        rx = x + (w - rw) / 2
        ry = y
    return slide.shapes.add_picture(
        _resolve(path), Inches(rx), Inches(ry), width=Inches(rw), height=Inches(rh)
    )


def add_image(slide, path, x, y, w, h, *, crop=True, placeholder="IMAGE", quiet=False):
    """Place an image, or a placeholder when it is missing or unreadable.

    ``quiet`` draws nothing but the label. A boxed placeholder is right for a
    large area such as a step photograph, where the gap should be obvious, but
    wrong for a small inline cutout, where the box is more distracting than the
    absence it marks.
    """
    if exists(path):
        try:
            return (
                add_picture_crop(slide, path, x, y, w, h)
                if crop
                else add_picture_contain(slide, path, x, y, w, h)
            )
        except Exception:
            pass

    if not quiet:
        add_box(slide, x, y, w, h, C["grey"], C["line"], radius=True)
    add_text(
        slide,
        placeholder,
        x + 0.05,
        y + h / 2 - 0.13,
        w - 0.10,
        0.26,
        font_size=9,
        color=C["muted"],
        bold=True,
        align="center",
    )
    return None


def add_circle_image(slide, path, cx, cy, d, fallback=""):
    circle = slide.shapes.add_shape(
        MSO_SHAPE.OVAL,
        Inches(cx - d / 2),
        Inches(cy - d / 2),
        Inches(d),
        Inches(d),
    )
    circle.fill.solid()
    circle.fill.fore_color.rgb = rgb(C["white"] if exists(path) else C["cream"])
    circle.line.color.rgb = rgb(C["border"])
    circle.line.width = Pt(0.6)

    # python-pptx cannot directly mask an image to an ellipse. Use a cropped square
    # image placed inside the circle; with ingredient cutout PNGs this reads visually
    # as the same circular ingredient treatment while remaining editable.
    if exists(path):
        pad = 0.025
        add_image(
            slide,
            path,
            cx - d / 2 + pad,
            cy - d / 2 + pad,
            d - 2 * pad,
            d - 2 * pad,
            crop=True,
            placeholder=fallback,
        )
    else:
        add_text(
            slide,
            (fallback[:1] or "?").upper(),
            cx - d / 2,
            cy - 0.11,
            d,
            0.22,
            font_size=8.5,
            color=C["line"],
            bold=True,
            align="center",
        )
