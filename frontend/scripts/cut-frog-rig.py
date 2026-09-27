"""Cut the frog into puppet layers, all the full canvas size, so every layer
stacks exactly and transform origins are plain canvas coordinates."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

SRC = str(Path(__file__).resolve().parents[1] / "public/mascot/frog-astronaut-2d.png")
OUT = str(Path(__file__).resolve().parents[1] / "public/mascot/rig") + "/"
im = np.array(Image.open(SRC).convert("RGBA")).astype(np.int32)
H, W = im.shape[:2]
R, G, B, A = im[..., 0], im[..., 1], im[..., 2], im[..., 3]
yy, xx = np.mgrid[0:H, 0:W]
opaque = A > 10

def poly(points):
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).polygon(points, fill=1)
    return np.array(m).astype(bool)

# Frog skin, including the yellow-green fingertips; the cream suit has G-B < 40.
green = (G > B + 40) & (R < G + 45) & (G > 90) & opaque

def piece(region, seed_colour, grow=16):
    """The seed colour inside `region`, grown to take in its dark keyline and
    white sticker outline, and kept inside `region`."""
    seed = seed_colour & region
    seed = ndimage.binary_opening(seed, iterations=2)
    grown = ndimage.binary_dilation(seed, iterations=grow) & opaque & region
    return ndimage.binary_fill_holes(grown)

# Waving hand (screen right): everything above the wrist line (910,405)-(1010,435),
# kept left of the swoosh marks.
hand_r_region = poly([(830, 190), (1122, 190), (1122, 400), (1036, 412), (1015, 452),
                      (905, 420), (860, 440), (830, 430)])
hand_r = piece(hand_r_region, green)

# Lower hand (screen left): below/left of the cuff line (95,880)-(245,955).
hand_l_region = poly([(0, 860), (90, 870), (140, 890), (250, 950), (250, 1090), (0, 1090)])
hand_l = piece(hand_l_region, green)

# Tongue: the pink.
pink = (R > 170) & (R - G > 55) & (R - B > 40) & (G > 60) & opaque
tongue_region = poly([(360, 470), (560, 470), (560, 640), (360, 640)])
tongue = piece(tongue_region, pink, grow=5)

# Motion marks, isolated strokes in open sky.
def marks(box):
    x0, y0, x1, y1 = box
    m = np.zeros((H, W), bool)
    m[y0:y1, x0:x1] = True
    return m & opaque
marks_head = marks((610, 0, 740, 110))
marks_hand = marks((1036, 412, 1110, 500))
marks_foot_r = marks((955, 1070, 1020, 1170))
marks_foot_l = marks((585, 1320, 650, 1395))

def save(mask, name):
    out = np.zeros_like(im)
    out[mask] = im[mask]
    Image.fromarray(out.astype(np.uint8)).save(OUT + name + ".webp", quality=90, method=6)

import os
os.makedirs(OUT, exist_ok=True)
for mask, name in ((hand_r, "hand-r"), (hand_l, "hand-l"), (tongue, "tongue"),
                   (marks_head, "marks-head"), (marks_hand, "marks-hand"),
                   (marks_foot_r | marks_foot_l, "marks-feet")):
    save(mask, name)

# The body: every moving part removed. Behind the tongue, the mouth's own dark
# red so a small wag never shows a hole; behind the hands, open sky.
base = im.copy()
removed = hand_r | hand_l | marks_head | marks_hand | marks_foot_r | marks_foot_l
base[removed] = 0
# Sweep the specks of outline the cut leaves where the hands were: any small
# island of pixels inside either hand's region.
alpha = base[..., 3] > 10
labels, n = ndimage.label(alpha)
sizes = ndimage.sum(alpha, labels, range(1, n + 1))
near = hand_r_region | hand_l_region
for i, size in enumerate(sizes, start=1):
    if size < 600 and (near & (labels == i)).any():
        base[labels == i] = 0
mouth = np.array([120, 28, 30, 255])
base[tongue] = mouth
Image.fromarray(base.astype(np.uint8)).save(OUT + "body.webp", quality=90, method=6)
print({n: int(m.sum()) for n, m in (("hand_r", hand_r), ("hand_l", hand_l), ("tongue", tongue))})
