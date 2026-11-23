"""Pack the rendered layers (render_web.py) into the website's truck files (tools/README.md):

    blender -b --factory-startup -P tools/truck/pack_web.py -- <layers dir> truck

Every layer is linear light one stop down (Standard view, exposure -1), stored as sRGB bytes with
straight alpha; the page (truck.js) decodes them, works in linear light and puts the stop back.

  base_A, base_B           the truck, white and black paint: its colors from the render on the
                           ground (so its chrome reflects the floor), its shape from the one without
  door_A_k, door_B_k       k = 1..frames: the door's area only, at that much open
  wheels_k                 k = 0..frames-1: the front wheels' area, full left to full right
  lights                  the light the headlights add, on the truck, in the air and on the floor
                           (opaque: black is none); the page moves it with the truck
  poster.webp              the truck as it first shows, for a browser without JavaScript
  truck.json               where each crop goes, the frame counts, the truck's middle and ground,
                           and the dark disk the page draws under it (from render_web.py's disk.json)
"""
import bpy, sys, os, json, glob, colorsys
import numpy as np

argv = sys.argv[sys.argv.index('--') + 1:]
SRC, DST = argv[0], argv[1]
os.makedirs(DST, exist_ok=True)
THRESH = 1.5 / 255.0
QUALITY = 88
FADE = 150.0                     # the beams fade out this far from the render's edges
PAINT = (0.0, 1.0, 0.873)        # the color the truck starts in: hue, saturation, value (the scene's red)
SCALE = 2.0                      # the stop the renders were taken down

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
    return to_lin(img[..., :3]) * img[..., 3:4]

def save(arr, name):
    """arr: top-first (h, w, 4) in 0..1, saved as lossy WebP with alpha."""
    h, w = arr.shape[:2]
    img = bpy.data.images.new(name, w, h, alpha=True, float_buffer=False)
    img.colorspace_settings.name = 'Non-Color'
    img.pixels.foreach_set(np.flipud(np.clip(arr, 0, 1)).astype(np.float32).ravel())
    img.file_format = 'WEBP'
    path = os.path.join(DST, name + '.webp')
    img.filepath_raw = path
    img.save(filepath=path, quality=QUALITY)
    bpy.data.images.remove(img)
    return os.path.getsize(path)

def opaque(lin):
    """Light to add, stored opaque: black is none."""
    out = np.ones(lin.shape[:2] + (4,), dtype=np.float32); out[..., :3] = to_enc(lin)
    return out

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

def truck_only(on_ground, shape):
    """The truck: its colors as rendered on the ground, its alpha from the render without it."""
    out = on_ground.copy(); out[..., 3] = shape[..., 3]
    return out

frames_door = len(glob.glob(os.path.join(SRC, 'door_A_*.png'))) - 1
frames_wheels = len(glob.glob(os.path.join(SRC, 'wheels_*.png')))
sizes = {}

# --- the truck ----------------------------------------------------------------------------
GA, GB, T0 = load('door_A_0'), load('door_B_0'), load('door_T_0')
H, W = GA.shape[:2]
A, B = truck_only(GA, T0), truck_only(GB, T0)
a_t = T0[..., 3]
sizes['base_A'] = save(A, 'base_A'); sizes['base_B'] = save(B, 'base_B')

# the door: one crop for every frame, round all that any frame changes
doors = {}
for k in range(1, frames_door + 1):
    t = load('door_T_%d' % k)
    doors[k] = (truck_only(load('door_A_%d' % k), t), truck_only(load('door_B_%d' % k), t))
changed = np.zeros((H, W), dtype=bool)
for a, b in doors.values():
    changed |= (np.abs(premul(a) - premul(A)).max(-1) > THRESH) | (np.abs(premul(b) - premul(B)).max(-1) > THRESH) \
               | (np.abs(a[..., 3] - A[..., 3]) > THRESH)
door_rect = bbox(changed)
for k, (a, b) in doors.items():
    sizes['door_A_%d' % k] = save(crop(a, door_rect), 'door_A_%d' % k)
    sizes['door_B_%d' % k] = save(crop(b, door_rect), 'door_B_%d' % k)

# the front wheels: one crop round every steer
wheels = {k: load('wheels_%d' % k) for k in range(frames_wheels)}
seen = np.zeros((H, W), dtype=bool)
for wl in wheels.values():
    seen |= wl[..., 3] > THRESH
wheel_rect = bbox(seen)
for k, wl in wheels.items():
    sizes['wheels_%d' % k] = save(crop(wl, wheel_rect), 'wheels_%d' % k)

# --- where the truck is: its ground line, its middle (where its button sits) ----------------
mid = len(wheels) // 2
solid = (a_t > 0.5) | (wheels[mid][..., 3] > 0.5)
ys, xs = np.nonzero(solid)
truck_rect = bbox(solid, pad=0)
cx, cy = float(xs.mean()), float(ys.mean())
ground_y = int(ys.max())

# --- the disk under the truck: where render_web.py found it (disk.json), how dark at its middle.
# Greg, 22 November 2026: the floor "needs to just be a disk with very feathered edges that's darker
# than the page background" - in place of the rendered floor, its orange and the reflection.
# The page draws it (truck.js): black, `dark` out to `core` of its radius, feathered from there to
# nothing at its edge. Most of it is behind the truck, so the feather starts early or it barely shows
yy, xx = np.mgrid[0:H, 0:W]
def ease(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)
fade = ease(np.minimum(np.minimum(xx, W - 1 - xx), np.minimum(yy, H - 1 - yy)) / FADE)
with open(os.path.join(SRC, 'disk.json')) as f:
    disk = json.load(f)
disk['dark'], disk['core'] = 0.7, 0.3
def disk_alpha():
    r = np.sqrt(((xx - disk['cx']) / disk['rx']) ** 2 + ((yy - disk['cy']) / disk['ry']) ** 2)
    return disk['dark'] * (1.0 - ease((r - disk['core']) / (1.0 - disk['core'])))

# --- the lights: what the lights-on render adds. All of it goes with the truck, glow and beams and
# the pools they throw on the floor: in the still ground layer, the glow round a lamp stayed behind
# when the truck squashed or leaned
L = np.clip(premul(load('lights_on')) - premul(GB), 0.0, None) * fade[..., None]
lights_rect = bbox(L.max(-1) > 0.5 / 255.0)
sizes['lights'] = save(crop(opaque(L), lights_rect), 'lights')

# --- the poster: the truck as truck.js first composes it, on its ground, the lights on ----------
def shoulder(c):
    """Khronos PBR Neutral's highlight compression (its toe left out: the page's dark stays)."""
    start = 0.8 - 0.04; d = 1.0 - start
    peak = c.max(-1, keepdims=True)
    new = 1.0 - d * d / (peak + d - start)
    k = np.where(peak > start, new / np.maximum(peak, 1e-6), 1.0)
    g = np.where(peak > start, 1.0 - 1.0 / (0.15 * (peak - new) + 1.0), 0.0)
    return (c * k) * (1 - g) + new * g

paint = np.array(colorsys.hsv_to_rgb(*PAINT), dtype=np.float32)   # Blender's HSV node: linear values
tp = premul(B) + paint * (premul(A) - premul(B)); ta = a_t
wp, wa = premul(wheels[mid]), wheels[mid][..., 3]
tp = wp + tp * (1 - wa[..., None]); ta = wa + ta * (1 - wa)
tp = tp + L
color = SCALE * tp
glow = np.clip(color.max(-1), 0.0, 1.0)
alpha = np.maximum(ta, glow)
alpha = alpha + disk_alpha() * (1 - alpha)                       # the disk, black, under it all
color = shoulder(color)
straight = np.where(alpha[..., None] > 1e-4, color / np.maximum(alpha[..., None], 1e-4), 0.0)
sizes['poster'] = save(np.concatenate([to_enc(straight), alpha[..., None]], -1), 'poster')

manifest = {
    'size': [W, H], 'scale': SCALE, 'paint': PAINT,
    'door': {'rect': door_rect, 'frames': frames_door},
    'wheels': {'rect': wheel_rect, 'frames': frames_wheels},
    'disk': disk,
    'lights': {'rect': lights_rect},
    'truck': {'rect': truck_rect, 'center': [round(cx, 1), round(cy, 1)], 'ground': ground_y},
}
with open(os.path.join(DST, 'truck.json'), 'w') as f:
    json.dump(manifest, f, indent=1)
print('manifest', json.dumps(manifest))
print('bytes', sum(sizes.values()), 'files', len(sizes))
