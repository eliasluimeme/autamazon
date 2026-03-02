import sys
from PIL import Image, ImageDraw, ImageFont
img = Image.new("RGBA", (200, 100), (255, 255, 255, 255))
draw = ImageDraw.Draw(img)
try:
    draw.text((10, 10), "TEST", fill=(255,255,255), stroke_width=2, stroke_fill=(0,0,0))
    print("Supports stroke")
except Exception as e:
    print(f"Error: {e}")
