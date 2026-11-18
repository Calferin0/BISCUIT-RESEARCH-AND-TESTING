"""One-off: cut Tony out of his grey studio backdrop and slim the GLB for phones.

Usage: py -3.14 -I tools/make_mascot.py <assets dir> <out dir>   (needs Pillow; not an app dependency)
"""
import io
import json
import struct
import sys
from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter

src, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)

# ---- 1. PNG cut-out ---------------------------------------------------------------------
BG = (59, 59, 59)
im = Image.open(src / "Tony.png").convert("RGBA")
W, H = im.size
px = im.load()


def dist(p):
    return max(abs(p[0] - BG[0]), abs(p[1] - BG[1]), abs(p[2] - BG[2]))


# Flood fill from the border over "background-ish" pixels, so dark paint *inside* Tony
# (navy stripe, moustache) can never be eaten: it isn't connected to the edge.
HI = 30
bg = bytearray(W * H)
q = deque()
for x in range(W):
    q.append((x, 0)); q.append((x, H - 1))
for y in range(H):
    q.append((0, y)); q.append((W - 1, y))
while q:
    x, y = q.popleft()
    i = y * W + x
    c = px[x, y]
    # Background is neutral grey: anything with colour (navy paint) is never background.
    if bg[i] or dist(c) > HI or max(c[:3]) - min(c[:3]) > 7:
        continue
    bg[i] = 1
    if x > 0: q.append((x - 1, y))
    if x < W - 1: q.append((x + 1, y))
    if y > 0: q.append((x, y - 1))
    if y < H - 1: q.append((x, y + 1))

mask = Image.new("L", (W, H), 255)
mp = mask.load()
LO = 6
for y in range(H):
    for x in range(W):
        if bg[y * W + x]:
            d = dist(px[x, y])
            mp[x, y] = 0 if d <= LO else int(255 * (d - LO) / (HI - LO))
# Shave the 1 px grey fringe and soften the edge slightly.
mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.7))
im.putalpha(mask)
bbox = mask.point(lambda v: 255 if v > 8 else 0).getbbox()
pad = 6
im = im.crop((bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad))
print("cut-out size", im.size)


def fit(img, h):
    w = round(img.width * h / img.height)
    return img.resize((w, h), Image.LANCZOS)


fit(im, 640).save(out / "tony.png", optimize=True)
fit(im, 96).save(out / "tony-96.png", optimize=True)
# Square favicon
ico = fit(im, 64)
sq = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
sq.paste(ico, ((64 - ico.width) // 2, 0), ico)
sq.save(out / "tony-favicon.png", optimize=True)

# ---- 2. Slim GLB: keep geometry + base colour only, base colour at 1024 px -------------
d = (src / "Tony.glb").read_bytes()
jlen = struct.unpack("<I", d[12:16])[0]
gj = json.loads(d[20:20 + jlen])
bin_off = 20 + jlen + 8
binc = d[bin_off:]

base_img_idx = gj["textures"][gj["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]["index"]]["source"]
base_bv = gj["images"][base_img_idx]["bufferView"]

new_bin = bytearray()
new_bvs = []
remap = {}


def add(chunk, extra):
    while len(new_bin) % 4:
        new_bin.append(0)
    bv = {"buffer": 0, "byteOffset": len(new_bin), "byteLength": len(chunk)}
    bv.update(extra)
    new_bin.extend(chunk)
    new_bvs.append(bv)
    return len(new_bvs) - 1


for acc in gj["accessors"]:
    old = gj["bufferViews"][acc["bufferView"]]
    if acc["bufferView"] not in remap:
        s = old.get("byteOffset", 0)
        extra = {k: v for k, v in old.items() if k in ("target", "byteStride")}
        remap[acc["bufferView"]] = add(binc[s:s + old["byteLength"]], extra)
    acc["bufferView"] = remap[acc["bufferView"]]

old = gj["bufferViews"][base_bv]
s = old.get("byteOffset", 0)
tex = Image.open(io.BytesIO(binc[s:s + old["byteLength"]])).convert("RGB")
print("base colour texture", tex.size)
if tex.width > 1024:
    tex = tex.resize((1024, round(tex.height * 1024 / tex.width)), Image.LANCZOS)
buf = io.BytesIO()
tex.save(buf, "JPEG", quality=84, optimize=True)
img_bv = add(buf.getvalue(), {})

gj["bufferViews"] = new_bvs
gj["images"] = [{"bufferView": img_bv, "mimeType": "image/jpeg"}]
gj["textures"] = [{"sampler": 0, "source": 0}]
mat = gj["materials"][0]
mat.pop("normalTexture", None)
mat.pop("occlusionTexture", None)
mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}
while len(new_bin) % 4:
    new_bin.append(0)
gj["buffers"] = [{"byteLength": len(new_bin)}]

js = json.dumps(gj, separators=(",", ":")).encode()
js += b" " * (-len(js) % 4)
glb = (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(new_bin))
       + struct.pack("<II", len(js), 0x4E4F534A) + js
       + struct.pack("<II", len(new_bin), 0x004E4942) + bytes(new_bin))
(out / "tony.glb").write_bytes(glb)
for f in sorted(out.iterdir()):
    print(f.name, f.stat().st_size)
