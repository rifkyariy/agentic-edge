"""One table, two renderings: a markdown table and a standalone SVG image.

results_tables.py builds every table once as a Tab and writes both, so the
text in findings/TABLES.md and the images in findings/tables/ cannot drift
apart. Cells are strings; **bold** and `code` marks are honoured in both.

The SVG is a self-contained figure: booktabs rules, tabular numerals,
numbers right-aligned, the proposed system's column or row tinted (as the
paper shades it), and its own light and dark palette (prefers-color-scheme).
png() renders it at 2x through headless Chrome when Chrome is installed.
Stdlib only.
"""
import os
import re
import shutil
import subprocess
from xml.sax.saxutils import escape

# Surfaces and ink from the dataviz reference palette; the tint is
# categorical slot 1 (blue) mixed into the surface, for the proposed system.
LIGHT = {"bg": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "rule": "#0b0b0b",
         "hair": "#e4e3df", "tint": "#e8f0fa", "group": "#f3f2ee"}
DARK = {"bg": "#1a1a19", "ink": "#ffffff", "ink2": "#c3c2b7", "rule": "#c3c2b7",
        "hair": "#34332f", "tint": "#1d2a3b", "group": "#242321"}
FONT = "Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
SIZE, HEAD_SIZE, TITLE_SIZE, NOTE_SIZE = 13, 12, 15, 11.5
PAD_X, ROW_H, HEAD_H, GROUP_H, MARGIN = 12, 27, 30, 24, 20
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

_W = {**{c: .556 for c in "0123456789"}, " ": .278, ".": .278, ",": .278, ":": .278, ";": .278,
      "·": .278, "'": .191, "|": .26, "i": .222, "l": .222, "j": .222, "f": .278, "t": .278,
      "r": .333, "m": .833, "w": .722, "W": .944, "M": .833, "I": .278, "%": .889, "±": .584,
      "–": .556, "—": 1.0, "/": .278, "(": .333, ")": .333, "+": .584, "=": .584, "°": .4,
      "×": .584, "≥": .584, "-": .333, "_": .556, "*": .389, "→": 1.0}


def width(text, size=SIZE, bold=False):
    w = sum(_W.get(c, .68 if c.isupper() else .54) for c in text) * size
    return w * (1.07 if bold else 1.0)


def plain(cell):
    """('text without marks', bold?)"""
    s = str(cell)
    bold = "**" in s
    return s.replace("**", "").replace("`", ""), bold


MARKS = "ᵃᵇᵈᵉᶠ✝"


def is_number(text):
    t = text.strip().rstrip(MARKS).strip()
    return bool(re.match(r"^[−+\-]?[\d,]+(\.\d+)?(%| ± [\d.]+| \(.*\)|/\d+| · .*)?$", t)) or t in ("—", "–", "-")


class Tab:
    """A table. rows may hold a ("group", label) tuple for a section divider.

    groups:    [(label, span), ...] over the header — a spanning header row
    shade:     column indices tinted as the proposed system
    shade_rows: row indices tinted as the proposed system
    bold:      {(row, col)} cells to set bold (best in row/column)
    """

    def __init__(self, name, title, head, rows, caption="", groups=None, shade=(), shade_rows=(),
                 bold=(), align=None):
        self.name, self.title, self.head, self.rows = name, title, head, rows
        self.caption, self.groups = caption, groups
        self.shade, self.shade_rows, self.bold = set(shade), set(shade_rows), set(bold)
        data = [r for r in rows if not isinstance(r, tuple)]
        self.align = align or ["l"] + ["r" if all(is_number(plain(r[c])[0]) for r in data) else "l"
                                       for c in range(1, len(head))]

    def cell(self, r, c):
        v = self.rows[r][c]
        return "**%s**" % v if (r, c) in self.bold and "**" not in str(v) else str(v)

    # ------------------------------------------------------------ markdown
    def md(self):
        head = list(self.head)
        if self.groups:
            i = 1 if self.groups[0][0] == "" else 0
            col = 0
            for label, span in self.groups:
                for k in range(span):
                    if label and col < len(head):
                        head[col] = "%s %s" % (label, head[col])
                    col += 1
        out = ["| " + " | ".join(head) + " |",
               "|" + "|".join("---:" if a == "r" else "---" for a in self.align) + "|"]
        for r, row in enumerate(self.rows):
            if isinstance(row, tuple):
                out.append("| *%s* |" % row[1] + " |" * (len(self.head) - 1))
            else:
                out.append("| " + " | ".join(self.cell(r, c) for c in range(len(row))) + " |")
        text = "\n".join(out) + "\n"
        if self.caption:
            text += "\n" + self.caption + "\n"
        return text

    # ------------------------------------------------------------ svg
    def svg(self):
        n = len(self.head)
        data = [(r, row) for r, row in enumerate(self.rows) if not isinstance(row, tuple)]
        cw = []
        for c in range(n):
            w = width(self.head[c], HEAD_SIZE, True)
            for r, row in data:
                t, b = plain(self.cell(r, c))
                w = max(w, width(t, SIZE, b))
            cw.append(w + 2 * PAD_X)
        if self.groups:                       # a spanning label must fit its columns
            col = 0
            for label, span in self.groups:
                need = width(label, HEAD_SIZE, True) + 2 * PAD_X
                have = sum(cw[col:col + span])
                if need > have:
                    for k in range(col, col + span):
                        cw[k] += (need - have) / span
                col += span
        for r, row in enumerate(self.rows):   # divider labels sit in the first column
            if isinstance(row, tuple):
                cw[0] = max(cw[0], width(row[1], SIZE, True) + 2 * PAD_X)
        tw = sum(cw)
        x0 = [MARGIN + sum(cw[:c]) for c in range(n)]
        title_y = MARGIN + TITLE_SIZE
        top = title_y + 14
        y = top + (GROUP_H if self.groups else 0)
        head_y = y
        body_top = head_y + HEAD_H
        body_h = sum(GROUP_H if isinstance(row, tuple) else ROW_H for row in self.rows)
        bottom = body_top + body_h
        notes = wrap(self.caption, tw * 0.94, NOTE_SIZE) if self.caption else []
        H = bottom + (14 + len(notes) * (NOTE_SIZE + 5) if notes else 0) + MARGIN
        W = max(tw, width(plain(self.title)[0], TITLE_SIZE, True) * 1.04) + 2 * MARGIN
        o = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" '
             'aria-label="%s">' % (W, H, W, H, escape(plain(self.title)[0]))]
        o.append("<style>%s</style>" % _css())
        o.append('<rect class="bg" width="100%" height="100%"/>')
        o.append('<text class="title" x="%d" y="%d">%s</text>' % (MARGIN, title_y, escape(plain(self.title)[0])))
        # tints, drawn under everything else
        for c in sorted(self.shade):
            o.append('<rect class="tint" x="%.1f" y="%.1f" width="%.1f" height="%.1f"/>'
                     % (x0[c], head_y, cw[c], bottom - head_y))
        yy = body_top
        for r, row in enumerate(self.rows):
            h = GROUP_H if isinstance(row, tuple) else ROW_H
            if isinstance(row, tuple):
                o.append('<rect class="group" x="%d" y="%.1f" width="%.1f" height="%d"/>' % (MARGIN, yy, tw, h))
                o.append('<text class="glabel" x="%.1f" y="%.1f">%s</text>'
                         % (MARGIN + PAD_X, yy + h / 2 + 4.5, escape(row[1])))
            elif r in self.shade_rows:
                o.append('<rect class="tint" x="%d" y="%.1f" width="%.1f" height="%d"/>' % (MARGIN, yy, tw, h))
            yy += h
        # spanning group header
        if self.groups:
            col = 0
            for label, span in self.groups:
                if label:
                    gx, gw = x0[col], sum(cw[col:col + span])
                    o.append('<text class="head" x="%.1f" y="%.1f" text-anchor="middle">%s</text>'
                             % (gx + gw / 2, top + GROUP_H / 2 + 4, escape(label)))
                    o.append('<line class="hair2" x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f"/>'
                             % (gx + 6, gx + gw - 6, top + GROUP_H - 1, top + GROUP_H - 1))
                col += span
        for c in range(n):
            xx = x0[c] + (cw[c] - PAD_X if self.align[c] == "r" else PAD_X)
            o.append('<text class="head" x="%.1f" y="%.1f"%s>%s</text>'
                     % (xx, head_y + HEAD_H / 2 + 4, ' text-anchor="end"' if self.align[c] == "r" else "",
                        escape(self.head[c])))
        # booktabs rules
        o.append('<line class="rule" x1="%d" x2="%.1f" y1="%.1f" y2="%.1f" stroke-width="1.5"/>' % (MARGIN, MARGIN + tw, top, top))
        o.append('<line class="rule" x1="%d" x2="%.1f" y1="%.1f" y2="%.1f" stroke-width="0.8"/>' % (MARGIN, MARGIN + tw, body_top, body_top))
        o.append('<line class="rule" x1="%d" x2="%.1f" y1="%.1f" y2="%.1f" stroke-width="1.5"/>' % (MARGIN, MARGIN + tw, bottom, bottom))
        yy = body_top
        for r, row in enumerate(self.rows):
            h = GROUP_H if isinstance(row, tuple) else ROW_H
            if not isinstance(row, tuple):
                for c in range(n):
                    t, b = plain(self.cell(r, c))
                    xx = x0[c] + (cw[c] - PAD_X if self.align[c] == "r" else PAD_X)
                    o.append('<text class="cell%s" x="%.1f" y="%.1f"%s>%s</text>'
                             % (" b" if b else "", xx, yy + h / 2 + 4.5,
                                ' text-anchor="end"' if self.align[c] == "r" else "", escape(t)))
                nxt = r + 1 < len(self.rows) and not isinstance(self.rows[r + 1], tuple)
                if nxt:
                    o.append('<line class="hair" x1="%d" x2="%.1f" y1="%.1f" y2="%.1f"/>'
                             % (MARGIN, MARGIN + tw, yy + h, yy + h))
            yy += h
        ny = bottom + 14 + NOTE_SIZE
        for line in notes:
            o.append('<text class="note" x="%d" y="%.1f">%s</text>' % (MARGIN, ny, escape(line)))
            ny += NOTE_SIZE + 5
        o.append("</svg>")
        return "\n".join(o) + "\n", (W, H)


def _css():
    def block(p):
        return (".bg{fill:%(bg)s}.title{fill:%(ink)s}.head{fill:%(ink2)s}.cell{fill:%(ink)s}"
                ".note{fill:%(ink2)s}.glabel{fill:%(ink2)s}.rule{stroke:%(rule)s}.hair{stroke:%(hair)s}"
                ".hair2{stroke:%(ink2)s}.tint{fill:%(tint)s}.group{fill:%(group)s}" % p)
    return ("text{font-family:%s;font-variant-numeric:tabular-nums}"
            ".title{font-size:%gpx;font-weight:600}.head{font-size:%gpx;font-weight:600}"
            ".cell{font-size:%gpx}.cell.b{font-weight:700}.note{font-size:%gpx}"
            ".glabel{font-size:%gpx;font-weight:600;font-style:italic}"
            ".hair{stroke-width:0.6}.hair2{stroke-width:0.6}" % (FONT, TITLE_SIZE, HEAD_SIZE, SIZE, NOTE_SIZE, SIZE)
            + block(LIGHT) + "@media (prefers-color-scheme:dark){" + block(DARK) + "}")


def wrap(text, w, size):
    words, lines, cur = text.replace("**", "").replace("`", "").split(), [], ""
    for word in words:
        trial = (cur + " " + word).strip()
        if width(trial, size) > w and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + ([cur] if cur else [])


def png(svg_path, size, out_path):
    """2x PNG of an SVG through headless Chrome, always the light palette (a
    figure for a paper or slide); False when Chrome is absent."""
    chrome = CHROME if os.path.exists(CHROME) else shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        return False
    with open(svg_path) as fh:
        # the dark block is the last thing in <style>: "@media (...){.a{..}...}}"
        light = re.sub(r"@media \(prefers-color-scheme:dark\)\{.*?\}\}", "", fh.read(), flags=re.S)
    tmp = out_path + ".light.svg"
    with open(tmp, "w") as fh:
        fh.write(light)
    try:
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                        "--window-size=%d,%d" % size, "--screenshot=" + out_path, "file://" + os.path.abspath(tmp)],
                       check=True, capture_output=True, timeout=60)
    finally:
        os.remove(tmp)
    return True
