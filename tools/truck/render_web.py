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
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
OUT = argv[0]
MODE = argv[1] if len(argv) > 1 else 'preview'
RES = int(argv[2]) if len(argv) > 2 else 900
EXPOSURE = -1.0            # one stop down: linear values to 2.0 fit in the 8 bits, the page puts it back
os.makedirs(OUT, exist_ok=True)

scene = bpy.context.scene
O = bpy.data.objects
body, door = O['Carpaint'], O['DL']

# --- the camera: three-quarter front, from the truck's left (+X), a little above --------------
cam_data = bpy.data.cameras.new('Web Camera')
cam_data.lens = 50.0
cam = bpy.data.objects.new('Web Camera', cam_data)
scene.collection.objects.link(cam)
target = Vector((0.0, -3.05, 1.45))
direction = Vector((0.82, -1.0, 0.36)).normalized()
cam.location = target + direction * 12.0
cam.rotation_euler = (target - cam.location).to_track_quat('-Z', 'Y').to_euler()
cam_data.shift_x, cam_data.shift_y = 0.0, 0.0
scene.camera = cam

r = scene.render
r.resolution_x = r.resolution_y = RES
r.resolution_percentage = 100
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
