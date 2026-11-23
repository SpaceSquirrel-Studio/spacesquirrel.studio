"""Render the truck's layers for the website's interactive graphic (truck.js), from the truck's
saved .blend, opened in a background Blender and never saved (tools/README.md):

    blender -b SemitruckCarToon.blend --factory-startup -P tools/truck/render_web.py -- <out dir> <mode> [width]

mode "preview": one render of the framing, as the scene looks (AgX), with the ground.
mode "layers":  every layer, linear light (Standard view, EXPOSURE stops down for headroom):
  door_A_k / door_B_k  the truck on its ground, white / black paint, lights off, front wheels unseen,
                       the left door open k / DOOR_FRAMES (k = 0 is shut)
  door_T_k             the same without the ground: the truck's own shape, for its alpha
  lights_on            door_B_0 with the lights on (the page takes door_B_0 from it: the lights' light)
  wheels_k             the front wheels alone (everything else a holdout), steered from full left
                       (k = 0) to full right (k = STEER_FRAMES - 1)
pack_web.py turns them into the page's files.
"""
import bpy, sys, os, math
from mathutils import Vector, Matrix

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
OUT = argv[0]
MODE = argv[1] if len(argv) > 1 else 'preview'
RES = int(argv[2]) if len(argv) > 2 else 1000           # the width; the frame is 5:4
EXPOSURE = -1.0            # one stop down: linear values to 2.0 fit in the 8 bits, the page puts it back
# The page shows the nearest frame, never a blend of two. Greg, 22 November 2026: "as I use the
# controls there are these semi transparent in-between frames that are very disorienting"
DOOR_FRAMES = 16           # the door's positions past shut
STEER_FRAMES = 17          # the wheels' positions, full left to full right
os.makedirs(OUT, exist_ok=True)

scene = bpy.context.scene
O = bpy.data.objects
body, door, ground = O['Carpaint'], O['DL'], O['Plane']

# --- the camera: Greg's viewport, low at the truck's front left -----------------------------------
# Greg: "The top down 3/4 is disorienting. We need to be looking at from the attached angle", then
# "the truck needs to look like it's sitting flat on the page" with his viewport lowered to 1.8 m and
# all but level. His 3D View's view matrix, read from Blender, then made exactly level (no roll).
# Its 50 mm viewport lens frames twice a 36 mm sensor's width (Blender's perspective views are
# zoomed out 2x), so the camera starts at 25 mm; frame_truck() then zooms it in.
VIEW = Matrix(((0.86695, 0.0045, 0.49837, 4.00288),
               (0.49839, -0.01136, -0.86688, -9.95538),
               (0.00176, 0.99993, -0.01209, 1.81667),
               (0.0, 0.0, 0.0, 1.0)))
look = -(VIEW.to_3x3().col[2]).normalized()
right = look.cross(Vector((0.0, 0.0, 1.0))).normalized()
up = right.cross(look)
LEVEL = Matrix((right, up, -look)).transposed().to_4x4()
LEVEL.translation = VIEW.translation
cam_data = bpy.data.cameras.new('Web Camera')
cam_data.lens = 25.0
cam_data.sensor_width = 36.0
cam_data.sensor_fit = 'HORIZONTAL'
cam = bpy.data.objects.new('Web Camera', cam_data)
scene.collection.objects.link(cam)
cam.matrix_world = LEVEL
scene.camera = cam

r = scene.render
r.resolution_x, r.resolution_y = RES, RES * 4 // 5
r.resolution_percentage = 100

# --- framing: from that same spot, zoomed in until the truck fills WIDTH of the frame or all but
# TOP and FLOOR of its height, whichever comes first, centered across, its wheels FLOOR above the
# bottom: room for its shadow and reflection on the ground below it
WIDTH, TOP, FLOOR = 0.82, 0.08, 0.15
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
    k = min(WIDTH / (max(xs) - min(xs)), (1.0 - TOP - FLOOR) / (max(ys) - min(ys)))
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
setp(body, 'Steer', 0.0); setp(door, 'Open', 0.0)
setp(body, 'Paint Saturation', 0.0)

def paint(white):
    setp(body, 'Paint Brightness', 1.0 if white else 0.0)

def lights(on):
    setp(body, 'Lights', 1.0 if on else 0.0)

# the body on its ground: the front wheels unseen by the camera, still casting their shadows
for n in FRONT:
    O[n].visible_camera = False
lights(False)
for k in range(DOOR_FRAMES + 1):
    setp(door, 'Open', k / DOOR_FRAMES)
    ground.hide_render = False
    for white in (True, False):
        paint(white)
        render('door_%s_%d' % ('A' if white else 'B', k))
    ground.hide_render = True
    render('door_T_%d' % k)
ground.hide_render = False
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
for k in range(STEER_FRAMES):
    setp(body, 'Steer', -1.0 + 2.0 * k / (STEER_FRAMES - 1))
    render('wheels_%d' % k)
print('held out', len(held), flush=True)
