"""Mixed CJK text with rounded numeral runs, measured exactly as rendered."""
import re
from math import ceil, floor
from PIL import Image, ImageColor, ImageDraw, ImageFont

_NUMBERS = re.compile(r"([0-9]+(?:[.,:/-][0-9]+)*%?)")
# BattleTags stay in one face so the discriminator does not jump to the numeral font.
_TOKENS = re.compile(r"(#?[A-Za-z][A-Za-z0-9_#.'\-]*|#[0-9]+|[0-9]+(?:[.,:/-][0-9]+)*%?)")
_SUPERSAMPLE = 4
_SMALL_TEXT_SIZE = 16
_MASK_CACHE_MAX = 2048
_MASKS = {}


class SummaryDraw(ImageDraw.ImageDraw):
    def __init__(self, image, mode=None, *, numeric_font_path):
        super().__init__(image, mode)
        self.numeric_font_path = str(numeric_font_path)
        self._numeric_fonts = {}

    def numeric_font(self, size):
        if size not in self._numeric_fonts:
            try:
                self._numeric_fonts[size] = ImageFont.truetype(self.numeric_font_path, size)
            except OSError:
                self._numeric_fonts[size] = None
        return self._numeric_fonts[size]

    def _runs(self, text, font):
        """Return (part, font) pairs, or None when one font renders the text."""
        if not _NUMBERS.search(str(text)):
            return None
        numeric = self.numeric_font(getattr(font, "size", 16))
        if numeric is None:
            return None
        return [(part, numeric if _NUMBERS.fullmatch(part) else font) for part in filter(None, _NUMBERS.split(str(text)))]

    def _layout(self, xy, text, font, anchor, stroke_width=0):
        if font is None or "\n" in str(text):
            return None
        pairs = self._runs(text, font)
        if pairs is None:
            return None
        cursor, runs, boxes = 0., [], []
        for part, selected in pairs:
            box = super().textbbox((cursor,0), part, font=selected, anchor="ls", stroke_width=stroke_width)
            boxes.append(box)
            runs.append((cursor,part,selected))
            cursor += selected.getlength(part)
        bounds=(min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes))
        anchor=anchor or "la"
        x,y=xy
        x -= {"l":0,"m":cursor/2,"r":cursor}.get(anchor[0],0)
        vertical=anchor[1]
        if vertical=="a": y+=font.getmetrics()[0]
        elif vertical=="t": y-=bounds[1]
        elif vertical=="m": y-=(bounds[1]+bounds[3])/2
        elif vertical=="b": y-=bounds[3]
        elif vertical=="d": y-=font.getmetrics()[1]
        return runs,(x,y),tuple(v+(x if i%2==0 else y) for i,v in enumerate(bounds)),cursor

    def _draw_run(self, xy, part, font, fill, **kwargs):
        super().text(xy,part,fill=fill,font=font,anchor="ls",**kwargs)

    def text(self, xy, text, fill=None, font=None, anchor=None, **kwargs):
        layout=self._layout(xy,text,font,anchor,kwargs.get("stroke_width",0))
        if layout is None:
            return super().text(xy,text,fill=fill,font=font,anchor=anchor,**kwargs)
        runs,(x,y),_,_=layout
        for offset,part,selected in runs:
            self._draw_run((x+offset,y),part,selected,fill,**kwargs)

    def textbbox(self, xy, text, font=None, anchor=None, **kwargs):
        layout=self._layout(xy,text,font,anchor,kwargs.get("stroke_width",0))
        if layout is None:
            return super().textbbox(xy,text,font=font,anchor=anchor,**kwargs)
        return layout[2]

    def textlength(self, text, font=None, **kwargs):
        layout=self._layout((0,0),text,font,None)
        return layout[3] if layout else super().textlength(text,font=font,**kwargs)


def _rounded_outline_mask(width, height, radius, stroke):
    big = Image.new("L", (width * _SUPERSAMPLE, height * _SUPERSAMPLE), 0)
    pen = ImageDraw.Draw(big)
    scaled = radius * _SUPERSAMPLE
    pen.rounded_rectangle((0, 0, big.width - 1, big.height - 1), radius=scaled, fill=255)
    if stroke:
        inset = stroke * _SUPERSAMPLE
        pen.rounded_rectangle((inset, inset, big.width - 1 - inset, big.height - 1 - inset),
                              radius=max(0, scaled - inset), fill=0)
    return big.reduce(_SUPERSAMPLE)


def smooth_mask(width, height, radius, stroke=0):
    """Anti-aliased rounded mask; large panels are nine-sliced to avoid 4x canvases."""
    width, height, stroke = int(width), int(height), int(stroke)
    radius = min(float(radius), width / 2, height / 2)
    key = (width, height, radius, stroke)
    mask = _MASKS.get(key)
    if mask is not None:
        return mask
    corner = ceil(max(radius, stroke)) + 2
    if width * height < 40000 or width <= corner * 2 + 1 or height <= corner * 2 + 1:
        mask = _rounded_outline_mask(width, height, radius, stroke)
    else:
        tile = _rounded_outline_mask(corner * 2 + 1, corner * 2 + 1, radius, stroke)
        mask = Image.new("L", (width, height), 0 if stroke else 255)
        span_x, span_y = width - corner * 2, height - corner * 2
        mask.paste(tile.crop((0, 0, corner, corner)), (0, 0))
        mask.paste(tile.crop((corner + 1, 0, corner * 2 + 1, corner)), (width - corner, 0))
        mask.paste(tile.crop((0, corner + 1, corner, corner * 2 + 1)), (0, height - corner))
        mask.paste(tile.crop((corner + 1, corner + 1, corner * 2 + 1, corner * 2 + 1)), (width - corner, height - corner))
        mask.paste(tile.crop((corner, 0, corner + 1, corner)).resize((span_x, corner)), (corner, 0))
        mask.paste(tile.crop((corner, corner + 1, corner + 1, corner * 2 + 1)).resize((span_x, corner)), (corner, height - corner))
        mask.paste(tile.crop((0, corner, corner, corner + 1)).resize((corner, span_y)), (0, corner))
        mask.paste(tile.crop((corner + 1, corner, corner * 2 + 1, corner + 1)).resize((corner, span_y)), (width - corner, corner))
    if len(_MASKS) >= _MASK_CACHE_MAX:
        _MASKS.clear()
    _MASKS[key] = mask
    return mask


def _flatten_points(xy):
    values = list(xy)
    if values and isinstance(values[0], (int, float)):
        return list(zip(values[0::2], values[1::2]))
    return [tuple(point) for point in values]


class SmoothDraw(SummaryDraw):
    """Summary text plus anti-aliased shapes on an opaque canvas.

    Latin names use a proportional face because simhei's half-width glyphs read as
    letter-spaced. Bold CJK is emulated when no real bold cut is available.
    """

    def __init__(self, image, mode=None, *, numeric_font_path, latin_font_path):
        super().__init__(image, mode, numeric_font_path=numeric_font_path)
        self.canvas = image
        self.latin_font_path = str(latin_font_path)
        self._latin_fonts = {}
        self._emulate_bold = False

    def latin_font(self, size):
        if size not in self._latin_fonts:
            try:
                self._latin_fonts[size] = ImageFont.truetype(self.latin_font_path, size)
            except OSError:
                self._latin_fonts[size] = None
        return self._latin_fonts[size]

    def _runs(self, text, font):
        text = str(text)
        size = getattr(font, "size", None)
        if not text or size is None or getattr(font, "path", "") == self.numeric_font_path:
            return None
        # Display faces such as BigNoodle are chosen for their own Latin and digits.
        if getattr(font, "keep_face", False):
            return None
        latin = self.latin_font(size) or font
        # The heavy numeral face fills in at small sizes.
        numeric = latin if size < _SMALL_TEXT_SIZE else self.numeric_font(size) or font
        runs = []
        for part in filter(None, _TOKENS.split(text)):
            if not _TOKENS.fullmatch(part):
                runs.append((part, font))
            else:
                runs.append((part, numeric if part[0].isdigit() else latin))
        return runs

    def _draw_run(self, xy, part, font, fill, **kwargs):
        super()._draw_run(xy, part, font, fill, **kwargs)
        if self._emulate_bold and getattr(font, "path", "") != self.numeric_font_path:
            super()._draw_run((xy[0] + .45, xy[1]), part, font, fill, **kwargs)

    def text(self, xy, text, fill=None, font=None, anchor=None, **kwargs):
        self._emulate_bold = bool(getattr(font, "emulate_bold", False))
        try:
            return super().text(xy, text, fill=fill, font=font, anchor=anchor, **kwargs)
        finally:
            self._emulate_bold = False

    def _paint(self, x, y, mask, fill):
        color = ImageColor.getrgb(fill) if isinstance(fill, str) else tuple(fill)
        alpha = color[3] if len(color) > 3 else 255
        if alpha < 255:
            mask = mask.point([value * alpha // 255 for value in range(256)])
        self.canvas.paste(color[:3], (x, y, x + mask.width, y + mask.height), mask)

    def _stamp(self, points, padding, fill, paint):
        left = floor(min(point[0] for point in points)) - padding
        top = floor(min(point[1] for point in points)) - padding
        right = ceil(max(point[0] for point in points)) + padding + 1
        bottom = ceil(max(point[1] for point in points)) + padding + 1
        left, top = max(0, left), max(0, top)
        right, bottom = min(self.canvas.width, right), min(self.canvas.height, bottom)
        if right <= left or bottom <= top:
            return
        big = Image.new("L", ((right - left) * _SUPERSAMPLE, (bottom - top) * _SUPERSAMPLE), 0)
        paint(ImageDraw.Draw(big), [((x - left) * _SUPERSAMPLE, (y - top) * _SUPERSAMPLE) for x, y in points])
        self._paint(left, top, big.reduce(_SUPERSAMPLE), fill)

    def rounded_rectangle(self, xy, radius=0, fill=None, outline=None, width=1, *, corners=None):
        if corners is not None:
            return super().rounded_rectangle(xy, radius, fill, outline, width, corners=corners)
        (x1, y1), (x2, y2) = _flatten_points(xy)
        x1, y1, x2, y2 = round(x1), round(y1), round(x2), round(y2)
        box_w, box_h = x2 - x1 + 1, y2 - y1 + 1
        if box_w <= 0 or box_h <= 0:
            return None
        if fill is not None:
            self._paint(x1, y1, smooth_mask(box_w, box_h, radius), fill)
        if outline is not None and width > 0:
            self._paint(x1, y1, smooth_mask(box_w, box_h, radius, width), outline)
        return None

    def ellipse(self, xy, fill=None, outline=None, width=1):
        (x1, y1), (x2, y2) = _flatten_points(xy)
        scale = _SUPERSAMPLE
        if fill is not None:
            self._stamp([(x1, y1), (x2 + 1, y2 + 1)], 1, fill, lambda pen, pts: pen.ellipse((*pts[0], *pts[1]), fill=255))
        if outline is not None and width > 0:
            self._stamp([(x1, y1), (x2 + 1, y2 + 1)], 1, outline,
                        lambda pen, pts: pen.ellipse((*pts[0], *pts[1]), outline=255, width=max(1, round(width * scale))))

    def arc(self, xy, start, end, fill=None, width=1):
        (x1, y1), (x2, y2) = _flatten_points(xy)
        self._stamp([(x1, y1), (x2 + 1, y2 + 1)], 1, fill,
                    lambda pen, pts: pen.arc((*pts[0], *pts[1]), start, end, fill=255, width=round(width * _SUPERSAMPLE)))

    def polygon(self, xy, fill=None, outline=None, width=1):
        points = _flatten_points(xy)
        if fill is not None:
            self._stamp(points, 1, fill, lambda pen, pts: pen.polygon(pts, fill=255))
        if outline is not None:
            self._stamp(points + points[:1], 2, outline,
                        lambda pen, pts: pen.line(pts, fill=255, width=max(1, round(width * _SUPERSAMPLE)), joint="curve"))

    def line(self, xy, fill=None, width=0, joint=None):
        points = _flatten_points(xy)
        if isinstance(width, int) and len(points) == 2 and (points[0][0] == points[1][0] or points[0][1] == points[1][1]):
            if len(tuple(fill)) < 4 or isinstance(fill, str):
                return super().line(xy, fill=fill, width=width, joint=joint)
            # Pillow stores alpha unblended on an RGBA canvas, turning hairlines opaque.
            (x1, y1), (x2, y2) = sorted((round(x), round(y)) for x, y in points)
            before = max(0, width - 1) // 2
            after = max(1, width) - before
            left, top = (x1, y1 - before) if y1 == y2 else (x1 - before, y1)
            size = (x2 - x1 + 1, after + before) if y1 == y2 else (after + before, y2 - y1 + 1)
            self._paint(left, top, Image.new("L", size, 255), fill)
            return None
        self._stamp(points, ceil(width) + 1, fill,
                    lambda pen, pts: pen.line(pts, fill=255, width=max(1, round(width * _SUPERSAMPLE)), joint="curve"))
        return None
