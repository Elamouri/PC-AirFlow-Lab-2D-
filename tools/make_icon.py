"""Draw the app icon (a case fan) and save assets/app.ico (all Windows sizes) and assets/app.png."""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N = 1024


def blade(cx, cy, r_in, r_out, a0, sweep=0.95, width=0.62):
    pts = []
    for k in range(12):
        s = k / 11
        r = r_in + (r_out - r_in) * s
        a = a0 + sweep * s
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    for k in range(12):
        s = 1 - k / 11
        r = r_in + (r_out - r_in) * s
        a = a0 + sweep * s + width * (0.55 + 0.45 * s)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def draw():
    img = Image.new('RGBA', (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((40, 40, N - 40, N - 40), radius=210, fill=(15, 20, 32, 255), outline=(42, 50, 71, 255),
                        width=18)
    cx = cy = N / 2
    glow = Image.new('RGBA', (N, N), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((cx - 400, cy - 400, cx + 400, cy + 400), fill=(90, 200, 250, 70))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(60)))
    d = ImageDraw.Draw(img)
    d.ellipse((cx - 392, cy - 392, cx + 392, cy + 392), fill=(21, 26, 37, 255), outline=(90, 200, 250, 255), width=22)
    for k in range(7):
        a0 = -math.pi / 2 + 2 * math.pi * k / 7
        col = (90, 200, 250, 255) if k % 2 == 0 else (64, 156, 230, 255)
        d.polygon(blade(cx, cy, 118, 352, a0), fill=col)
    d.ellipse((cx - 130, cy - 130, cx + 130, cy + 130), fill=(233, 237, 245, 255))
    d.ellipse((cx - 62, cy - 62, cx + 62, cy + 62), fill=(255, 107, 90, 255))       # warm centre = heat
    return img


def main():
    os.makedirs(os.path.join(HERE, 'assets'), exist_ok=True)
    img = draw()
    img.resize((256, 256), Image.LANCZOS).save(os.path.join(HERE, 'assets', 'app.png'))
    img.save(os.path.join(HERE, 'assets', 'app.ico'),
             sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
    print('saved assets/app.ico and assets/app.png')


if __name__ == '__main__':
    main()
