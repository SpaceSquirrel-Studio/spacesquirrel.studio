# Rebuilding the Kneady docs

The pages under `docs/` (the docs front page, the guide, Writing a tutorial,
and the clips in `docs/media/`) are made by `build_docs.py` from the Kneady
repository. **Don't edit them by hand:** the next build replaces them. Change
`docs/GUIDE.md`, `docs/TUTORIALS.md` or a `tutorial.json` in Kneady, then build
again. Edit `docs/docs.js` (the clip player) by hand; the build leaves it alone.

| File | What it is |
|---|---|
| `build_docs.py` | Makes every docs page from Kneady's `docs/` and `tutorials/` |
| `docs_config.json` | Which tutorial clips go in which part of the guide, and what is Pro-only |
| `bump_version.py` | Bumps the `?v=` number on every page after a CSS or JS change |
| `truck/render_web.py`, `truck/pack_web.py` | Make the home page's truck (`truck/`), from the truck's `.blend` |

## Remaking the truck on the home page

The truck you can hover and drag on the home page (`truck.js`) is a set of
renders in `truck/`: the truck with white and with black paint (so the page
can recolor it), the door at 16 more angles, the front wheels at 17 steering
angles (the page shows the nearest, never a blend of two), and the light the
headlights add, and a dark, feathered disk for the truck to stand on: a circle
on the ground round its tires (`DISK_CENTER`, `DISK_RADIUS` in meters, in
`render_web.py`), feathered by distance on the ground so it follows the
perspective. How dark it is, and how far out it stays that dark before it
fades, are `DARK` and `CORE` in `pack_web.py`. Remake them
after changing the truck in Blender. Rendering takes two to three minutes. The page
reads the frame counts and sizes from `truck/truck.json`, so it needs no change.

In **PowerShell** (Start menu, type `PowerShell`, open it), with the truck's
`.blend` saved:

1. Go to the site folder: `cd $HOME\Projects\spacesquirrel.studio`
2. Render the layers into a scratch folder (two to three minutes; Blender opens the
   file without a window and never saves it):
   `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b "<the truck's .blend>" --factory-startup -P tools/truck/render_web.py -- "$env:TEMP\truck_layers" layers 1000`
3. Pack them into `truck/`:
   `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b --factory-startup -P tools/truck/pack_web.py -- "$env:TEMP\truck_layers" truck`
4. Bump the version number, so browsers fetch the new renders instead of ones
   they kept (the page asks for the truck's files with it):
   `& "C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" tools/bump_version.py`
5. Look at it in a browser. The page can't read its files straight from disk,
   so serve the folder with the Python that comes with Blender:
   `& "C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" -m http.server 8000`
   then open http://localhost:8000 and press **Ctrl+C** in PowerShell when
   done. Publish as usual.

`render_web.py` looks from a camera copied from Greg's Blender viewport (`VIEW`
in the script), zoomed to fit the truck, and renders the scene as saved (its
environment, squash and rim color), setting the paint, lights, door and
steering itself. The color the truck starts in on the page is `PAINT` in
`pack_web.py`. To see the framing first, use `preview` in place of `layers`
in step 2: one render, as the scene looks.

## Each release

### The easy way: ask Claude

In a Claude chat linked to this computer, with `C:\Users\Greg\Projects\Kneady`
added as a folder, say:

> Rebuild the Kneady docs on spacesquirrel.studio from my Kneady folder,
> following tools/README.md, check the pages, and push.

### Doing it yourself

**Once, to set up** (in **PowerShell**: Start menu, type `PowerShell`, open
it):

1. Install Python from python.org. In the installer, tick **Add python.exe to
   PATH**.
2. Install ffmpeg: `winget install Gyan.FFmpeg`
3. Install the two Python packages: `python -m pip install markdown-it-py beautifulsoup4`
4. Get the site: `cd $HOME\Projects` then
   `git clone https://github.com/SpaceSquirrel-Studio/spacesquirrel.studio.git`
5. Close PowerShell and open it again, so it finds ffmpeg.

**Every release** (in **PowerShell**):

1. Go to the site folder and get the latest:
   `cd $HOME\Projects\spacesquirrel.studio` then `git pull`
2. Build: `python tools/build_docs.py --source $HOME\Projects\Kneady`
   It only reads your Kneady folder. New or changed clips are encoded; the
   rest are skipped. At the end it lists warnings, such as a tutorial with no
   summary. A message starting `build_docs:` means it stopped: usually a guide
   heading or clip was renamed. Fix the name in `tools/docs_config.json` and
   run it again.
3. Look at it: `python -m http.server 8000`, then open
   http://localhost:8000/docs/ in your browser. Press **Ctrl+C** in PowerShell
   to stop it.
4. Publish:
   `git add -A` then
   `git commit -m "Docs for Kneady 1.0.1"` (your version) then
   `git push`
   GitHub Pages updates the site a minute or two later.

If you changed `style.css`, `truck.js` or `docs/docs.js`, run
`python tools/bump_version.py` and then the build (step 2) again before you
publish, so browsers load the new files.

## What the build does

- **Guide** and **Writing a tutorial** come from `GUIDE.md` and `TUTORIALS.md`,
  read as GitHub reads Markdown, so links like `#toggles` keep working.
- **Clips** listed in `docs_config.json` are put into the guide as examples.
  Each `section` is a heading's id: the heading in lower case, spaces as `-`,
  punctuation dropped. `after` is how the paragraph or list item the clips
  follow starts. Leave `after` out to put the clips at the end of the section.
- **Web copies** of the clips: H.264, yuv420p, no sound, with the index at the
  front so they start playing at once (plays in Chrome, Safari and Firefox),
  plus a still of each clip's last frame. Clips the guide no longer uses are
  deleted. `docs/media/sources.json` remembers what was encoded.
- **Tutorials list** on the docs front page comes from each `tutorial.json`'s
  title, summary and order, numbered as Kneady's menu numbers them.
- **Pro-only:** a paragraph starting with a phrase in `pro_only` gets a
  **Pro** badge. Add phrases there when the guide describes Pro features.
- **Header and footer** are copied from `support.html`, so the docs follow the
  rest of the site when those change.
