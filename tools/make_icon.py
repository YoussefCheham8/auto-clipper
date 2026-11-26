"""Generate the Auto-Clipper .ico used by the build."""
import os
from PIL import Image, ImageDraw

SIZE = 256
icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(icon)

# rounded square with a diagonal gradient
mask = Image.new("L", (SIZE, SIZE), 0)
mask_draw = ImageDraw.Draw(mask)
mask_draw.rounded_rectangle((8, 8, SIZE - 8, SIZE - 8), radius=58, fill=255)
gradient = Image.new("RGBA", (SIZE, SIZE))
pixels = gradient.load()
for y in range(SIZE):
    for x in range(SIZE):
        t = (x + y) / (2 * SIZE)
        r = int(160 + (255 - 160) * t)
        g = int(107 + (95 - 107) * t)
        b = int(255 + (162 - 255) * t)
        pixels[x, y] = (r, g, b, 255)
icon.paste(gradient, (0, 0), mask)

# film-strip marks and a play triangle
line = (255, 255, 255, 205)
for x in (52, 204):
    for y in (56, 96, 160, 200):
        draw.rounded_rectangle((x - 7, y - 13, x + 7, y + 13), radius=4, fill=line)
draw.rounded_rectangle((78, 70, 178, 186), radius=20, outline=(255, 255, 255, 220), width=7)
draw.polygon([(111, 101), (111, 155), (153, 128)], fill=(255, 255, 255, 245))

out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
os.makedirs(out, exist_ok=True)
path = os.path.join(out, "app.ico")
icon.save(path, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print(path)
