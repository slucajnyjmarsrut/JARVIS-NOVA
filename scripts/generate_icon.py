"""Create a deterministic original app icon for Windows CI (no external assets)."""
from pathlib import Path
from PIL import Image, ImageDraw

path = Path(__file__).resolve().parent.parent / "assets" / "jarvis.ico"
path.parent.mkdir(parents=True, exist_ok=True)
canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
draw = ImageDraw.Draw(canvas)
draw.rounded_rectangle((16, 16, 240, 240), radius=48, fill=(16, 26, 49, 255), outline=(53, 203, 233, 255), width=9)
draw.arc((55, 55, 201, 198), start=235, end=80, fill=(77, 214, 241, 255), width=18)
draw.ellipse((139, 175, 164, 200), fill=(233, 246, 255, 255))
canvas.save(path, sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
print(f"Generated deterministic project icon at {path}")
