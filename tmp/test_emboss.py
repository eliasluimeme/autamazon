import sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# Create a font
try:
    font = ImageFont.truetype("/Users/elias/Documents/GitHub/amazon/data/DL/Australia-DL/Font/Tahoma.ttf", 50)
except:
    font = ImageFont.load_default()

# 1. Base text image
txt_img = Image.new("RGBA", (400, 100), (0, 0, 0, 0))
d = ImageDraw.Draw(txt_img)
d.text((10, 10), "9876543", font=font, fill=(180, 180, 180, 255))

# 2. Emboss requires converting to a non-RGBA mode or we apply it to alpha and colors carefully.
# Actually, the simplest fake glass/emboss is to draw the text multiple times slightly shifted.
# Top-Left highlight: White
# Bottom-Right shadow: Black
# Center: Semi-transparent white
out_img = Image.new("RGBA", (400, 100), (0, 0, 0, 0))
do = ImageDraw.Draw(out_img)

# Deep shadow
do.text((14, 14), "9876543", font=font, fill=(0, 0, 0, 150))
# Black outline
do.text((10, 9), "9876543", font=font, fill=(0, 0, 0, 200))
do.text((10, 11), "9876543", font=font, fill=(0, 0, 0, 200))
do.text((9, 10), "9876543", font=font, fill=(0, 0, 0, 200))
do.text((11, 10), "9876543", font=font, fill=(0, 0, 0, 200))
# Top-left highlight
do.text((9, 9), "9876543", font=font, fill=(255, 255, 255, 255))
# Center fill
do.text((10, 10), "9876543", font=font, fill=(200, 200, 200, 180))

out_img.save("emboss_test.png")
