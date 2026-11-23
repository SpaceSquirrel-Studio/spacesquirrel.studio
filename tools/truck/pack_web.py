"""Pack the rendered layers (render_web.py) into the website's truck files (tools/README.md):

    blender -b --factory-startup -P tools/truck/pack_web.py -- <layers dir> truck

Every layer is linear light one stop down (Standard view, exposure -1), stored as sRGB bytes with
straight alpha; the page decodes them, works in linear light and puts the stop back (truck.js).

  base_A.webp, base_B.webp  the whole truck, white and black paint (front wheels and lights apart)
  door_A_k / door_B_k       k = 1..8: the door's area only, at that much open
  wheels_k                  k = 0..8: the front wheels' area, steered (k - 4) / 4
  lights.webp               the light the headlights add, opaque (black is none)
  poster.webp               the truck as it first shows, for a browser without JavaScript
  truck.json                where each crop goes, and the truck's middle and ground
"""
import bpy, sys, os, json
import numpy as np

argv = sys.argv[sys.argv.index('--') + 1:]
SRC, DST = argv[0], argv[1]
os.makedirs(DST, exist_ok=True)
THRESH = 1.5 / 255.0
QUALITY = 88

def load(name):
    img = bpy.data.images.load(os.path.join(SRC, name + '.png'))
    img.colorspace_settings.name = 'Non-Color'             # the bytes as written, no conversion
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32); img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return np.flipud(px.reshape(h, w, 4)).copy()           # top row first

def to_lin(enc):
    return np.where(enc <= 0.04045, enc / 12.92, ((enc + 0.055) / 1.055) ** 2.4)

def to_enc(lin):
    lin = np.clip(lin, 0.0, 1.0)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)

def premul(img):
    return to_lin(img[..., :3]) * img[..., 3:4], img[..., 3]

def save(arr, name):
    """arr: top-first (h, w, 4) in 0..1, saved as lossy WebP with alpha."""
    h, w = arr.shape[:2]
    img = bpy.data.images.new(name, w, h, alpha=True, float_buffer=False)
    img.colorspace_settings.name = 'Non-Color'
    img.pixels.foreach_set(np.flipud(arr).astype(np.float32).ravel())
    img.file_format = 'WEBP'
    path = os.path.join(DST, name + '.webp')
    img.filepath_raw = path
    img.save(filepath=path, quality=QUALITY)
    bpy.data.images.remove(img)
    return os.path.getsize(path)

def bbox(mask, pad=3):
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    h, w = mask.shape
    x0, y0 = max(int(xs.min()) - pad, 0), max(int(ys.min()) - pad, 0)
    x1, y1 = min(int(xs.max()) + pad + 1, w), min(int(ys.max()) + pad + 1, h)
    return [x0, y0, x1 - x0, y1 - y0]

def crop(arr, r):
    x, y, w, h = r
    return arr[y:y + h, x:x + w]

sizes = {}
A, B = load('base_A'), load('base_B')
H, W = A.shape[:2]
sizes['base_A'] = save(A, 'base_A'); sizes['base_B'] = save(B, 'base_B')

# the door: one crop for every frame, round all that any frame changes
doors = {k: (load('door_A_%d' % k), load('door_B_%d' % k)) for k in range(1, 9)}
changed = np.zeros((H, W), dtype=bool)
for a, b in doors.values():
    changed |= (np.abs(a - A).max(-1) > THRESH) | (np.abs(b - B).max(-1) > THRESH)
door_rect = bbox(changed)
for k, (a, b) in doors.items():
    sizes['door_A_%d' % k] = save(crop(a, door_rect), 'door_A_%d' % k)
    sizes['door_B_%d' % k] = save(crop(b, door_rect), 'door_B_%d' % k)

# the front wheels: one crop round every steer
wheels = {k: load('wheels_%d' % k) for k in range(9)}
seen = np.zeros((H, W), dtype=bool)
for wl in wheels.values():
    seen |= wl[..., 3] > THRESH
wheel_rect = bbox(seen)
for k, wl in wheels.items():
    sizes['wheels_%d' % k] = save(crop(wl, wheel_rect), 'wheels_%d' % k)

# the lights: what the lights-on render adds to the black-paint truck, in linear light
on = load('lights_on')
on_p, on_a = premul(on); off_p, off_a = premul(B)
L = np.clip(on_p - off_p, 0.0, None)
# the beams run off the render's left and bottom edges: fade them out before they get there, or
# the page shows the render's edge as a hard line through them
FADE = 150.0
yy, xx = np.mgrid[0:H, 0:W]
edge = np.minimum(np.minimum(xx, W - 1 - xx), np.minimum(yy, H - 1 - yy)) / FADE
fade = np.clip(edge, 0.0, 1.0); fade = fade * fade * (3 - 2 * fade)
L *= fade[..., None]
lights_rect = bbox(L.max(-1) > 0.5 / 255.0)
lit = np.ones((H, W, 4), dtype=np.float32); lit[..., :3] = to_enc(L)
sizes['lights'] = save(crop(lit, lights_rect), 'lights')

# where the truck is: its ground, its middle (where its button sits), all it covers
body_a = A[..., 3]
solid = (body_a > 0.5) | (wheels[4][..., 3] > 0.5)
ys, xs = np.nonzero(solid)
truck_rect = bbox(solid, pad=0)
cx, cy = float(xs.mean()), float(ys.mean())
ground = int(ys.max())

# the poster: the paint as the scene has it, the lights on, as truck.js composes it
PAINT = (0.0, 1.0, 0.873)                                  # hue, saturation, value: the scene's red
import colorsys
paint = np.array(colorsys.hsv_to_rgb(*PAINT), dtype=np.float32)   # Blender's HSV node: linear values
Ap, Aa = premul(A); Bp, Ba = premul(B)
body = Bp + paint * (Ap - Bp); alpha = Aa
wp, wa = premul(wheels[4])
body = wp + body * (1 - wa[..., None]); alpha = wa + alpha * (1 - wa)
SCALE = 2.0                                                  # the stop the renders were taken down
color = SCALE * (body + L)
glow = np.clip(color.max(-1), 0.0, 1.0)
out_a = np.maximum(alpha, np.where(alpha < 1.0, glow, 0.0))

def shoulder(c):
    """Khronos PBR Neutral's highlight compression (its toe left out: the page's dark stays)."""
    start = 0.8 - 0.04; d = 1.0 - start
    peak = c.max(-1, keepdims=True)
    new = 1.0 - d * d / (peak + d - start)
    k = np.where(peak > start, new / np.maximum(peak, 1e-6), 1.0)
    c2 = c * k
    g = np.where(peak > start, 1.0 - 1.0 / (0.15 * (peak - new) + 1.0), 0.0)
    return c2 * (1 - g) + new * g

color = shoulder(color)
straight = np.where(out_a[..., None] > 1e-4, color / np.maximum(out_a[..., None], 1e-4), 0.0)
poster = np.concatenate([to_enc(straight), out_a[..., None]], -1)
sizes['poster'] = save(poster, 'poster')

manifest = {
    'size': [W, H], 'scale': SCALE, 'paint': PAINT,
    'door': {'rect': door_rect, 'frames': 8},
    'wheels': {'rect': wheel_rect, 'frames': 9},
    'lights': {'rect': lights_rect},
    'truck': {'rect': truck_rect, 'center': [round(cx, 1), round(cy, 1)], 'ground': ground},
}
with open(os.path.join(DST, 'truck.json'), 'w') as f:
    json.dump(manifest, f, indent=1)
print('manifest', json.dumps(manifest))
print('bytes', sum(sizes.values()), json.dumps(sizes))
