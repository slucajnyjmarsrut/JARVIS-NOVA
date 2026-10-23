"""Generate original dark sci-fi Inno Setup wizard bitmaps offline with Pillow.

Run on the Windows builder immediately after scripts/generate_icon.py.
No downloaded artwork, fonts or binary files from third-party websites.
"""
from pathlib import Path
import math

from PIL import Image, ImageDraw, ImageFont

NIGHT=(7,13,25)
CYAN=(73,231,241)
GLOW=(23,93,116)
WHITE=(230,251,255)


def _font(size):
    for path in ("C:/Windows/Fonts/segoeuib.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if Path(path).is_file():
            return ImageFont.truetype(path,size)
    return ImageFont.load_default()


def render_banner(path: Path):
    w,h=640,1220
    image=Image.new("RGB",(w,h),NIGHT)
    pixels=image.load()
    for y in range(h):
        shade=int(y/h*11)
        for x in range(w):
            pixels[x,y]=(7+shade//3,13+shade,25+shade*2)
    draw=ImageDraw.Draw(image)
    # Thin circuitry trace and cyan energy core.
    for idx in range(16):
        xpos=(idx*71)%w
        draw.line([(xpos,0),(xpos,h)],fill=(12,40,55),width=1)
    cx,cy=w//2,465
    for radius,shade,width in ((242,(19,62,80),2),(211,GLOW,3),
                                (179,(40,157,185),4),(146,CYAN,3),
                                (108,(32,131,154),5)):
        draw.ellipse((cx-radius,cy-radius,cx+radius,cy+radius),
                     outline=shade,width=width)
    for i in range(60):
        angle=math.tau*i/60
        radius=224
        xx=cx+math.cos(angle)*radius
        yy=cy+math.sin(angle)*radius
        draw.line((xx,yy,xx+math.cos(angle)*(21 if i%5==0 else 9),
                   yy+math.sin(angle)*(21 if i%5==0 else 9)),
                  fill=CYAN if i%5==0 else GLOW,width=3)
    draw.ellipse((cx-81,cy-81,cx+81,cy+81),fill=(12,42,58),
                 outline=CYAN,width=5)
    draw.text((cx,cy-52),"N",anchor="mt",fill=WHITE,font=_font(106),
              stroke_width=1,stroke_fill=GLOW)
    draw.text((cx,cy+56),"N O V A",anchor="mm",fill=CYAN,font=_font(23))
    draw.line((64,820,w-64,820),fill=GLOW,width=3)
    draw.text((64,846),"JARVIS",fill=WHITE,font=_font(76))
    draw.text((64,940),"NOVA  /  OFFLINE",fill=CYAN,font=_font(36))
    draw.text((64,1036),"VOICE   ·   LOCAL AI",fill=(115,186,203),
              font=_font(24))
    draw.text((64,1086),"WINDOWS  EDITION",fill=(115,186,203),
              font=_font(24))
    path.parent.mkdir(parents=True,exist_ok=True)
    image.save(path,format="BMP")


def render_badge(path: Path):
    w,h=240,240
    image=Image.new("RGB",(w,h),NIGHT)
    draw=ImageDraw.Draw(image)
    for r,shade,stroke in ((100,GLOW,5),(83,CYAN,4),(64,GLOW,3)):
        draw.ellipse((w//2-r,h//2-r,w//2+r,h//2+r),
                     outline=shade,width=stroke)
    draw.ellipse((76,76,164,164),fill=(16,62,78),outline=CYAN,width=3)
    draw.text((120,105),"N",font=_font(59),fill=WHITE,anchor="mm")
    draw.text((120,154),"NOVA",font=_font(19),fill=CYAN,anchor="mm")
    path.parent.mkdir(parents=True,exist_ok=True)
    image.save(path,format="BMP")


def generate(destination: Path):
    render_banner(destination/"installer_banner.bmp")
    render_badge(destination/"installer_badge.bmp")


if __name__=="__main__":
    generate(Path(__file__).resolve().parents[1]/"assets")
    print("NOVA dark Inno Setup graphics generated")
