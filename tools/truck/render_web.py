"""Render the truck's layers for the website's interactive graphic (truck.js), from the truck's
saved .blend, opened in a background Blender and never saved (tools/README.md):

    blender -b SemitruckCarToon.blend --factory-startup -P tools/truck/render_web.py -- <out dir> <mode> [size]

mode "preview": one render of the framing, as the scene looks (AgX), with the ground.
mode "layers":  every layer, linear light (Standard view, EXPOSURE stops down for headroom):
  base_A / base_B      the truck with white / black paint, door shut, lights off, front wheels unseen
  door_A_k / door_B_k  the same with the left door open k/8 (k = 1..8)
  wheels_k             the front wheels alone (everything else a holdout), steered (k - 4) / 4
  lights_on            base_B with the lights on (the page takes base_B from it: the lights' own light)
"""
import bpy, sys, os, math
from mathutils import Vector, Matrix

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
OUT = argv[0]
MODE = argv[1] if len(argv) > 1 else 'preview'
RES = int(argv[2]) if len(argv) > 2 else 1000           # the width; the frame is 5:4
EXPOSURE = -1.0            # one stop down: linear values to 2.0 fit in the 8 bits, the page puts it back
os.makedirs(OUT, exist_ok=True)

scene = bpy.context.scene
O = bpy.data.objects
body, door = O['Carpaint'], O['DL']

# --- the camera: Greg's viewport, 22 November 2026, low at the truck's front left ---------------
# Greg: "The top down 3/4 is disorienting. We need to be looking at from the attached angle." His
# 3D View's view matrix, read from Blender. Its 50 mm viewport lens frames twice a 36 mm sensor's
# width (Blender's perspective views are zoomed out 2x), so the camera is 25 mm, 72 degrees across.
VIEW = Matrix(((0.87214, -0.06116, 0.48541, 3.82223),
               (0.48881, 0.06691, -0.86982, -9.71989),
               (0.02072, 0.99588, 0.08825, 2.29237),
               (0.0, 0.0, 0.0, 1.0)))
cam_data = bpy.data.cameras.new('Web Camera')
cam_data.lens = 25.0
cam_data.sensor_width = 36.0
cam_data.sensor_fit = 'HORIZONTAL'
cam = bpy.data.objects.new('Web Camera', cam_data)
scene.collection.objects.link(cam)
cam.matrix_world = VIEW
scene.camera = cam

r = scene.render
r.resolution_x, r.resolution_y = RES, RES * 4 // 5
r.resolution_percentage = 100

# --- framing: from that same spot, zoomed in until the truck fills WIDTH of the frame, centered,
# its wheels FLOOR above the bottom, so the page has room to stretch it upward (truck.js)
WIDTH, FLOOR = 0.84, 0.06
def frame_truck():
    from bpy_extras.object_utils import world_to_camera_view
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    xs, ys = [], []
    for o in scene.objects:
        if o.type != 'MESH' or o.name in ('Plane', 'HDRI Controller') or o.hide_render:
            continue
        e = o.evaluated_get(dg); m = e.to_mesh(); mw = o.matrix_world
        for i in range(0, len(m.vertices), 3):
            p = world_to_camera_view(scene, cam, mw @ m.vertices[i].co)
            xs.append(p.x); ys.append(p.y)
        e.to_mesh_clear()
    k = WIDTH / (max(xs) - min(xs))
    aspect = r.resolution_x / r.resolution_y
    cam_data.lens *= k
    cam_data.shift_x = ((min(xs) + max(xs)) / 2 - 0.5) * k
    cam_data.shift_y = (0.5 + (min(ys) - 0.5) * k - FLOOR) / aspect
    print('framed: lens %.2f shift %.3f %.3f' % (cam_data.lens, cam_data.shift_x, cam_data.shift_y), flush=True)
frame_truck()
r.image_settings.file_format = 'PNG'
r.image_settings.color_mode = 'RGBA'
r.image_settings.color_depth = '16'

def setp(obj, key, value):
    obj[key] = value
    obj.update_tag()

def render(name):
    bpy.context.view_layer.update()
    r.filepath = os.path.join(OUT, name + '.png')
    bpy.ops.render.render(write_still=True)
    print('rendered', name, flush=True)

FRONT = ['RimF.L', 'RimF.R', 'TireF.L', 'TireF.R']

if MODE == 'preview':
    render('preview')
    sys.exit(0)

# --- the layers ---------------------------------------------------------------------------
r.film_transparent = True
scene.view_settings.view_transform = 'Standard'
scene.view_settings.look = 'None'
scene.view_settings.exposure = EXPOSURE
scene.view_settings.gamma = 1.0
O['Plane'].hide_render = True                                   # the page draws its own soft shadow
setp(body, 'Steer', 0.0); setp(door, 'Open', 0.0)
setp(body, 'Paint Saturation', 0.0)

def paint(white):
    setp(body, 'Paint Brightness', 1.0 if white else 0.0)

def lights(on):
    setp(body, 'Lights', 1.0 if on else 0.0)

# the body layers: the front wheels unseen by the camera, still casting their shadows
for n in FRONT:
    O[n].visible_camera = False
lights(False)
for k in range(9):
    setp(door, 'Open', k / 8.0)
    for white in (True, False):
        paint(white)
        render(('base_' if k == 0 else 'door_') + ('A' if white else 'B') + ('' if k == 0 else '_%d' % k))
setp(door, 'Open', 0.0)
paint(False); lights(True)
render('lights_on')
lights(False)

# the front wheels alone: everything else held out, so the body still hides what it covers
for n in FRONT:
    O[n].visible_camera = True
held = []
for o in scene.objects:
    if o.type in {'MESH', 'CURVE', 'VOLUME'} and o.name not in FRONT and not o.hide_render:
        o.is_holdout = True
        held.append(o.name)
for k in range(9):
    setp(body, 'Steer', (k - 4) / 4.0)
    render('wheels_%d' % k)
print('held out', len(held), flush=True)
