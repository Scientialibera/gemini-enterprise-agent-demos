"""Shared palette and layout measurements: geometry in inches, type in points."""

PAGE_W = 10.0
PAGE_H = 13.33
LEFT_W = 3.45
GAP = 0.28
RIGHT_X = LEFT_W + GAP
RIGHT_W = PAGE_W - RIGHT_X - 0.22
# The hero meets the blue panel and reaches the top and right page edges.
HERO_X = LEFT_W
HERO_W = PAGE_W - LEFT_W
HERO_H = 7.42
C = {
    # The header panel falls from blue_top to blue_bottom. The old flat 6F97C5
    # read as washed out against the navy and yellow and gave white type weak
    # contrast.
    "blue": "4F7DBF",
    "blue_top": "5C8BCB",
    "blue_bottom": "3A66AA",
    "blue_soft": "C9D8EE",
    "dark_blue": "07347A",
    "yellow": "F9B800",
    "yellow2": "FFC515",
    "ink": "1D2530",
    "muted": "5C6573",
    "pale": "F5F1E6",
    "line": "0D3D85",
    "white": "FFFFFF",
    "cream": "FBF8F0",
    "grey": "E8E8E8",
    "border": "D8D8D8",
    "accent": "0070C0",
}

# Page 1 header block. The title sits lower and wider than the panel's centre,
# so the panel ends above the servings pill rather than behind it.
HEADER_PANEL_H = 3.82
HEADER_TIME_ICON_D = 0.24
# Centred on the title below it rather than on the panel: the title box is
# inset slightly right of the panel, and the pot reads as its mark.
HEADER_POT_X = 1.77
HEADER_POT_Y = 1.25
TITLE_X = 0.25
TITLE_Y = 1.45
TITLE_W = 3.04
TITLE_H = 1.61
# A three-line title fills its box to 3.06, so the old 3.03 overlapped it. The
# subtitle clears the title and still ends inside the panel at 3.82.
# The subtitle sits higher and smaller, so two full lines fit above the
# servings pill instead of being cut off with an ellipsis.
SUBTITLE_Y = 3.00
SUBTITLE_W = 2.84
SUBTITLE_H = 0.54
SUBTITLE_FONT_SIZE = 15.0
# The pill straddles the panel's bottom edge, tying the header to the list.
SERVINGS_Y = HEADER_PANEL_H - 0.12
SERVINGS_TEXT_OFFSET = 0.08

# Overview right column.
CALLOUT_Y = 7.66
DESCRIPTION_FONT_SIZE = 9.0
DESCRIPTION_H = 0.42
MENU_TITLE_FONT_SIZE = 10.5
MENU_BLURB_W = 1.90
MENU_BLURB_H = 0.34
MENU_PICTURE_W = 2.33
# Where the menu photograph started when its accent shapes were drawn.
MENU_ACCENT_PICTURE_X = 7.27
MENU_PICTURE_H = 0.84
MENU_LABEL_OFFSET = 0.35

# Closing panels on the last steps page.
VARIATIONS_PANEL_OFFSET = 0.30
VARIATIONS_PANEL_H = 1.35
# Wide enough that PowerPoint's own font metrics cannot wrap the heading. At
# 2.60 the default title left 0.17in of slack, and a second line needs 0.73in
# in a 0.46in tab, so it spilled over the panel below it.
VARIATIONS_TAB_W = 3.00
# A line of the heading at its type size needs more than the hand-drawn box
# gave it: at 0.36in the text wrapped to two lines and spilled below the tab.
VARIATIONS_TAB_H = 0.46
# The heading reverses out of a filled tab overlapping the panel's top edge.
VARIATIONS_TAB_FILL = "1F497D"

# "Getting Started" holds two labelled lists between the description and the
# menu band. Each list flows across two columns so a long pantry list widens
# rather than running into the band below it.
GETTING_STARTED_COLUMNS = 2
GETTING_STARTED_COL_W = 1.28
GETTING_STARTED_COL_GAP = 0.06
GETTING_STARTED_LIST_FONT_SIZE = 10.2
GETTING_STARTED_LINE_H = 0.19
VARIATIONS_SKETCH_X = 7.00
BANNER_TEXT_X = 0.46
BANNER_TEXT_W = 3.56
BANNER_FONT_SIZE = 20.0
# Bold Georgia at banner size runs wider than HEAD_CHAR_WIDTH_RATIO assumes:
# a 47-character line it counted as two lines rendered as three.
BANNER_CHAR_WIDTH_RATIO = 0.55
HEAD_FONT = "Georgia"
BODY_FONT = "Aptos"
# Conservative mean character widths and line heights for fixed-size text.
CHAR_WIDTH_RATIO = 0.45
# Measured from rendered cards: Georgia headings set at about 0.55 of their
# size per character. At the old 0.41 a title counted as two lines set as
# three and ran into the subtitle beneath it.
HEAD_CHAR_WIDTH_RATIO = 0.55
BOLD_WIDTH_FACTOR = 1.12
LINE_HEIGHT_RATIO = 1.22
POINTS_PER_INCH = 72.0

# The headline takes the largest of these sizes that sets it in two lines.
TITLE_FONT_SIZES = (36.0, 30.0, 26.0)
TITLE_MAX_LINES = 2
# The callout heading takes one line, stepping down once before it is cut.
CALLOUT_FONT_SIZES = (20.0, 16.0)
# Characters per line of the tip in the body face, with the heading label
# counted as part of the first line.
TIP_CHARS_PER_LINE = 112
TIP_LINE_HEIGHT = 0.26
TIP_VERTICAL_PADDING = 0.30
INGREDIENT_FONT_SIZE = 10.0
# A short list spreads down the column with larger photographs rather than
# ending halfway and leaving the lower rail empty.
INGREDIENT_ROW_MAX_HEIGHT = 1.15
# Keep rows readable; additional ingredients go onto continuation pages.
INGREDIENT_ROW_MIN_HEIGHT = 0.46
INGREDIENT_PANEL_PADDING = 0.22
INGREDIENT_MAX_ROWS = 12
INGREDIENT_PANEL_TOP = 4.30
# The Seasonal Menu band on the overview, and the ingredient card that ends on
# the same line as it: two bottoms a few hundredths apart read as a misalignment.
MENU_BAND_Y = 11.62
INGREDIENT_PANEL_MAX_BOTTOM = MENU_BAND_Y + MENU_PICTURE_H
# The "continues" note sits clear of the card's shadow, not against its edge.
CONTINUES_NOTE_GAP = 0.10
STEP_IMAGE_WIDTH_FRACTION = 0.46
STEP_IMAGE_MIN_ASPECT = 1.05
# The tallest a step photograph may be, as height over width. A block that grew
# to fill its page used to drag the photograph with it, cropping a square
# image into a sliver more than twice as tall as it was wide.
STEP_IMAGE_MAX_PORTRAIT = 1.50
CHEF_NOTE_FONT_SIZE = 11.5
STEP_BLOCK_GAP = 0.24
STEP_BLOCK_MIN_HEIGHT = 2.60
# Bound expansion so a short page breathes without its blocks turning to air.
# Bound expansion so a short page breathes without its blocks turning to air.
STEP_BLOCK_MAX_SCALE = 1.50

# The compact layout: three steps across, each photograph under its text.
# It is used when it fits a recipe on fewer pages than the side-by-side one.
STACK_COLUMNS = 3
STACK_GAP = 0.30
STACK_PHOTO_ASPECT = 0.68
STACK_TITLE_FONT_SIZE = 15.0
STACK_TITLE_BOX_HEIGHT = 0.56
STACK_BLOCK_MAX_SCALE = 1.20

# The closing panels sit at the foot of the last steps page, above the footer:
# the variations, then the banner.
CLOSING_BOTTOM = 12.50
CLOSING_GAP = 0.24
BANNER_H = 1.08
# The customizations are written out in the variations panel when this much
# height holds them, rather than on pages of their own.
VARIATIONS_INLINE_MAX_H = 4.60
INLINE_FONT_SIZE = 9.5
INLINE_COLUMN_GAP = 0.30
STEP_BLOCK_COLUMN_SHARE = 0.58
# How much of a short column's leftover height its last block absorbs. Giving
# back all of it made the shorter block of a row end up taller than its
# neighbour, erasing the difference the measured heights had established.
STEP_COLUMN_SPARE_SHARE = 0.5
STEPS_PAGE_BOTTOM = 12.60
# Two lines of a title must fit the title box: at 20pt a wrapped title ran
# into the first instruction below it.
STEP_TITLE_FONT_SIZE = 17.0
# Each step number sits in a navy disc beside its title.
STEP_BADGE_D = 0.36
STEP_TITLE_INDENT = 0.46
STEP_TITLE_BOX_HEIGHT = 0.62
# A title that fits one line takes this much, so its checklist starts close
# under it instead of below an empty second line.
STEP_TITLE_ONE_LINE_H = 0.44
BULLET_FONT_SIZE = 10.0
BULLET_LINE_HEIGHT = 0.56
WORDS_PER_BULLET_LINE = 6
BULLET_ROW_PADDING = 0.10
# The least height an instruction takes, so one-line bullets keep a steady
# rhythm without the half-inch gaps a full row height left between them.
BULLET_MIN_HEIGHT = 0.36
# Instructions are measured this much narrower than their box; see
# steps._bullet_heights.
BULLET_WRAP_ALLOWANCE = 0.14
