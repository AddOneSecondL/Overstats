"""Mixed CJK text with rounded numeral runs, measured exactly as rendered."""
import re
from PIL import ImageDraw, ImageFont

_NUMBERS = re.compile(r"([0-9]+(?:[.,:/-][0-9]+)*%?)")


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

    def _layout(self, xy, text, font, anchor, stroke_width=0):
        if font is None or "\n" in str(text) or not _NUMBERS.search(str(text)):
            return None
        numeric = self.numeric_font(getattr(font, "size", 16))
        if numeric is None:
            return None
        cursor, runs, boxes = 0., [], []
        for part in filter(None, _NUMBERS.split(str(text))):
            selected = numeric if _NUMBERS.fullmatch(part) else font
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

    def text(self, xy, text, fill=None, font=None, anchor=None, **kwargs):
        layout=self._layout(xy,text,font,anchor,kwargs.get("stroke_width",0))
        if layout is None:
            return super().text(xy,text,fill=fill,font=font,anchor=anchor,**kwargs)
        runs,(x,y),_,_=layout
        for offset,part,selected in runs:
            super().text((x+offset,y),part,fill=fill,font=selected,anchor="ls",**kwargs)

    def textbbox(self, xy, text, font=None, anchor=None, **kwargs):
        layout=self._layout(xy,text,font,anchor,kwargs.get("stroke_width",0))
        if layout is None:
            return super().textbbox(xy,text,font=font,anchor=anchor,**kwargs)
        return layout[2]

    def textlength(self, text, font=None, **kwargs):
        layout=self._layout((0,0),text,font,None)
        return layout[3] if layout else super().textlength(text,font=font,**kwargs)
