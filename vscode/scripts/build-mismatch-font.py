"""Generate `resources/rbx-mismatch.woff`, the run view's mismatch icon font.

    uv run --with fonttools python scripts/build-mismatch-font.py

Why a font at all
-----------------
A tree row has exactly one icon slot, and #664 spent it on the verdict. The
expectation needs a second mark on the same row, and the only other channel --
`FileDecoration` -- cannot hold an icon: its `badge` is a `string`, not a
`ThemeIcon`. So the mismatch mark has to live *inside* the icon, which means a
glyph that does not exist in the codicon set.

Of the two ways to ship one, a contributed icon font beats SVG files: icons
contributed through `contributes.icons` are ordinary `ThemeIcon`s, so they take
a `ThemeColor` and follow the user's theme. An SVG referenced by `iconPath` is
an image, fixed at whatever colours are baked into it, which would have cost the
per-verdict palette this view shares with the terminal.

How the glyphs are built
------------------------
Each output glyph is a TrueType *composite*: the original codicon scaled down
and anchored bottom-left, plus a mark glyph scaled into the top-right corner.
Components reference the base outlines rather than copying them, so every icon
gets an identical mark and the font stays a few kilobytes.

The mark is `error` -- a circled cross -- rather than a bare `close` cross. That
is not a style preference: a tree row draws its icon at 16px, and at that size
the cross alone thins to a hairline that disappears against the base glyph,
while the circle gives the mark a closed shape that survives rasterisation.
Render `scripts/build-mismatch-font.py --preview` to check this after any change
to the scales below; judging them at 64px will mislead you.

Licensing
---------
The outlines come from VS Code's codicon font (microsoft/vscode-codicons),
CC BY 4.0. `resources/CODICONS-LICENSE.md` carries the attribution that licence
requires, and must ship alongside the generated font.
"""

import argparse
import pathlib
import re
import sys

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables import ttProgram
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphComponent

# Where VS Code keeps the codicon font and the stylesheet naming its icons. The
# stylesheet is the authority on icon *ids*: several ids are aliases pointing at
# another glyph's codepoint (`zap` is `symbol-event`, `alert` is `warning`), so
# resolving through it is the only way to reach the right outline.
VSCODE = pathlib.Path('/Applications/Visual Studio Code.app/Contents/Resources/app')
CSS = VSCODE / 'extensions/simple-browser/media/codicon.css'
TTF = VSCODE / 'out/media/codicon.ttf'

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'resources/rbx-mismatch.woff'

# Every verdict icon `outcome.ts` can draw on a row that has a report. `pending`
# (circle-outline) is deliberately absent: a row with no verdict yet cannot have
# missed an expectation, so a mismatch variant of it would be unreachable.
ICON_IDS = [
    'pass',
    'close',
    'watch',
    'debug-pause',
    'server',
    'zap',
    'arrow-both',
    'law',
    'alert',
    'tools',
    'debug-step-over',
    'question',
]

MARK_ID = 'error'

# Private Use Area, clear of the E000 block codicon itself occupies.
FIRST_CODEPOINT = 0xF500

# Tuned at 16px, which is the size that matters. See the module docstring.
BASE_SCALE = 0.72
MARK_SCALE = 0.55
# Vertical centre of the mark, as a fraction of the em square.
MARK_CENTRE_Y = 0.78
# Gap between the mark and the right edge, as a fraction of the em square.
MARK_INSET_X = 0.02


def icon_codepoints() -> dict[str, int]:
    css = CSS.read_text()
    return {
        name: int(code, 16)
        for name, code in re.findall(
            r'\.codicon-([a-z0-9-]+):before\s*{\s*content:\s*"\\([0-9a-fA-F]+)"', css
        )
    }


def mismatch_id(icon: str) -> str:
    return f'rbx-{icon}-mismatch'


def build() -> tuple[TTFont, dict[str, int], dict[str, str]]:
    if not TTF.exists() or not CSS.exists():
        sys.exit(f'VS Code assets not found under {VSCODE}. Is VS Code installed?')

    codepoints = icon_codepoints()
    missing = [i for i in [*ICON_IDS, MARK_ID] if i not in codepoints]
    if missing:
        sys.exit(f'codicon.css does not define: {", ".join(missing)}')

    font = TTFont(TTF)
    cmap = font.getBestCmap()
    glyph_of = {i: cmap[codepoints[i]] for i in [*ICON_IDS, MARK_ID]}

    options = subset.Options()
    options.glyph_names = True
    options.notdef_outline = True
    options.drop_tables += ['DSIG']
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=sorted({codepoints[i] for i in [*ICON_IDS, MARK_ID]}))
    subsetter.subset(font)

    glyf = font['glyf']
    hmtx = font['hmtx']
    upem = font['head'].unitsPerEm

    mark_glyph = glyph_of[MARK_ID]
    mark_box = glyf[mark_glyph]
    mark_w = (mark_box.xMax - mark_box.xMin) * MARK_SCALE
    mark_h = (mark_box.yMax - mark_box.yMin) * MARK_SCALE
    mark_x = int(upem - mark_w - upem * MARK_INSET_X)
    mark_y = int(upem * MARK_CENTRE_Y - mark_h * 0.5)

    assigned: dict[str, int] = {}
    for index, icon in enumerate(ICON_IDS):
        base = GlyphComponent()
        base.glyphName = glyph_of[icon]
        base.x, base.y = 0, 0
        base.transform = [[BASE_SCALE, 0], [0, BASE_SCALE]]
        base.flags = 0

        mark = GlyphComponent()
        mark.glyphName = mark_glyph
        mark.x, mark.y = mark_x, mark_y
        mark.transform = [[MARK_SCALE, 0], [0, MARK_SCALE]]
        mark.flags = 0

        glyph = Glyph()
        glyph.numberOfContours = -1
        glyph.components = [base, mark]
        glyph.program = ttProgram.Program()
        glyph.program.fromBytecode(b'')

        name = mismatch_id(icon)
        glyf[name] = glyph
        hmtx[name] = hmtx[glyph_of[icon]]
        assigned[icon] = FIRST_CODEPOINT + index

    # `glyf[name] = ...` already appended to glyf.glyphOrder; reuse that rather
    # than building a second order, which would duplicate the new names.
    font.setGlyphOrder(list(glyf.glyphOrder))
    for table in font['cmap'].tables:
        if table.isUnicode():
            for icon, codepoint in assigned.items():
                table.cmap[codepoint] = mismatch_id(icon)

    name_table = font['name']
    for name_id, value in (
        (1, 'rbx mismatch icons'),
        (4, 'rbx mismatch icons'),
        (6, 'rbx-mismatch-icons'),
    ):
        name_table.setName(value, name_id, 3, 1, 0x409)

    return font, assigned, glyph_of


def preview(font: TTFont, assigned: dict[str, int]) -> None:
    """Render base vs mismatch at the sizes a tree actually draws."""
    from PIL import Image, ImageDraw, ImageFont

    tmp = OUT.with_suffix('.preview.ttf')
    font.flavor = None
    font.save(tmp)
    codepoints = icon_codepoints()

    sizes = [16, 20, 32]
    cell = 46
    img = Image.new(
        'RGB', (140 + cell * 2 * len(sizes), 30 + cell * len(ICON_IDS)), '#1f1f1f'
    )
    draw = ImageDraw.Draw(img)
    label = ImageFont.load_default()
    for si, size in enumerate(sizes):
        draw.text((140 + si * cell * 2, 8), f'{size}px', fill='#888', font=label)
    for ri, icon in enumerate(ICON_IDS):
        y = 26 + ri * cell
        draw.text((8, y + 14), icon, fill='#ccc', font=label)
        for si, size in enumerate(sizes):
            base_font = ImageFont.truetype(str(TTF), size)
            mismatch_font = ImageFont.truetype(str(tmp), size)
            x = 140 + si * cell * 2
            draw.text(
                (x, y + 10), chr(codepoints[icon]), font=base_font, fill='#cccccc'
            )
            draw.text(
                (x + cell, y + 10),
                chr(assigned[icon]),
                font=mismatch_font,
                fill='#f14c4c',
            )
    out = OUT.with_suffix('.preview.png')
    img.save(out)
    tmp.unlink()
    print(f'wrote {out}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--preview', action='store_true', help='also render a PNG contact sheet'
    )
    args = parser.parse_args()

    font, assigned, glyph_of = build()
    if args.preview:
        preview(font, assigned)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    font.flavor = 'woff'
    font.save(OUT)
    print(f'wrote {OUT} ({OUT.stat().st_size} bytes)')
    print()
    print('contributes.icons entries:')
    for icon, codepoint in assigned.items():
        base = glyph_of[icon]
        alias = '' if base == icon else f'  (codicon `{icon}` is `{base}`)'
        print(f'  {mismatch_id(icon):32} \\\\{codepoint:04X}{alias}')


if __name__ == '__main__':
    main()
