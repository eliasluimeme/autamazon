from rembg import remove
from PIL import Image
import os

input_path = '/Users/elias/Documents/GitHub/amazon/data/DL/images/g7vnBjRxF1_QQHEF8KZTz_OyjkTOYw.png'
output_path = '/Users/elias/Documents/GitHub/amazon/outputs/dl/test_rembg.png'

input_img = Image.open(input_path).convert('RGBA')
output_img = remove(input_img)
output_img.save(output_path)
print(f"Saved to {output_path}")
