#!/usr/bin/env python3
"""Build the Kneady Controls docs pages of spacesquirrel.studio.

    python tools/build_docs.py --source PATH_TO_KNEADY

PATH_TO_KNEADY is a copy of the Kneady repository, or any folder holding its
docs/ and tutorials/ folders (blender_manifest.toml beside them, if there, gives
the version shown on the pages). Nothing is written there.

It (re)writes, in this site's docs/ folder:
    index.html                     the docs' front page, listing the tutorials Kneady ships
    guide/index.html               docs/GUIDE.md, with tutorial clips in it
    writing-a-tutorial/index.html  docs/TUTORIALS.md
    media/<name>/*.mp4, *.jpg      web copies of the clips the guide shows, and a still of each
    images/                        images the guide uses

Run it again for every release. Clips whose source has not changed are not
encoded again (docs/media/sources.json remembers them). Needs Python 3.9+,
ffmpeg, and: pip install markdown-it-py beautifulsoup4
See tools/README.md.
"""
import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from markdown_it import MarkdownIt
    from bs4 import BeautifulSoup, NavigableString
except ImportError:
    sys.exit("Missing packages. Run:  python -m pip install markdown-it-py beautifulsoup4")

SITE = Path(__file__).resolve().parent.parent
DOCS = SITE / "docs"
CONFIG = json.loads((Path(__file__).parent / "docs_config.json").read_text(encoding="utf-8"))
ENC = CONFIG["encode"]
ENC_KEY = f"h264-high-yuv420p-crf{ENC['crf']}-{ENC['preset']}-h{ENC['max_height']}-faststart-v1"

warnings = []


def warn(msg):
    warnings.append(msg)
    print("  ! " + msg)


def fail(msg):
    sys.exit("build_docs: " + msg)


def esc(s):
    return html.escape(str(s), quote=True)


def norm(el):
    return " ".join(el.get_text().split())


def slugify(text):
    """GitHub's heading ids, so links written for GitHub work here too."""
    s = text.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def url_slug(folder):
    return folder.replace("_", "-")


# ---------------------------------------------------------------- site shell

def site_shell():
    """Header, footer, fonts and the cache-busting number, taken from support.html
    so the docs follow the rest of the site when it changes."""
    page = BeautifulSoup((SITE / "support.html").read_text(encoding="utf-8"), "html.parser")
    css = page.find("link", rel="stylesheet", href=re.compile(r"style\.css"))
    m = re.search(r"\?v=(\d+)", css["href"]) if css else None
    if not m:
        fail("support.html links style.css without ?v=NNNNNN")
    version = m.group(1)

    def absolute(tag):
        for el in tag.find_all(href=True) + tag.find_all(src=True):
            for attr in ("href", "src"):
                v = el.get(attr)
                if v and not re.match(r"^(/|#|[a-z]+:)", v):
                    el[attr] = "/" + v
        return tag

    head = absolute(page.find("header", class_="site-head"))
    for a in head.find_all("a"):
        if a.get("href") == "/support.html":
            a["aria-current"] = "true"
        elif a.has_attr("aria-current"):
            del a["aria-current"]
    foot = absolute(page.find("footer", class_="site-foot"))
    fonts = "\n".join(str(l) for l in page.find_all("link")
                      if "fonts.g" in (l.get("href") or ""))
    return version, str(head), str(foot), fonts


def page_html(shell, title, description, body, crumbs, scripts=True):
    version, head, foot, fonts = shell
    trail = " <span aria-hidden=\"true\">/</span> ".join(
        f'<a href="{href}">{esc(label)}</a>' if href else f'<span aria-current="page">{esc(label)}</span>'
        for label, href in crumbs)
    js = f'\n<script src="/docs/docs.js?v={version}" defer></script>' if scripts else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — Kneady Controls docs</title>
<meta name="description" content="{esc(description)}">
<link rel="icon" href="/favicon-192.png" sizes="192x192" type="image/png">
<link rel="icon" href="/favicon-16.png" sizes="16x16" type="image/png">
<link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
{fonts}
<link rel="stylesheet" href="/style.css?v={version}">{js}
</head>
<body class="docs">
<!-- Made by tools/build_docs.py from the Kneady repository. Edit the source and build again. -->
<a class="skip" href="#main">Skip to content</a>
<div class="wrap">
  {head}

  <nav class="crumbs" aria-label="Breadcrumb">{trail}</nav>
  <main id="main">
{body}
  </main>

  {foot}
</div>
</body>
</html>
"""


# ---------------------------------------------------------------- media

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Media:
    def __init__(self, source):
        self.source = source
        self.cache_file = DOCS / "media" / "sources.json"
        self.cache = json.loads(self.cache_file.read_text()) if self.cache_file.exists() else {}
        self.used = set()
        self.ffmpeg = shutil.which("ffmpeg")
        if not self.ffmpeg:
            fail("ffmpeg isn't installed or isn't on PATH. See tools/README.md.")

    def clip(self, tut, item, fps_hint=None):
        """Web copy of one tutorial clip or image. Returns (src, poster, kind) or None."""
        name = item["file"]
        src = self.source / "tutorials" / tut / name
        ext = src.suffix.lower()
        kind = "image" if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif") else "video"
        if not src.exists():
            if item.get("hosted") or item.get("url"):
                warn(f"{tut}/{name} is hosted and not in the source: linking to it online, with no web copy")
                return None
            warn(f"{tut}/{name} is missing from the source (the tutorial shows 'not recorded yet')")
            return None
        out_dir = DOCS / "media" / tut
        out_dir.mkdir(parents=True, exist_ok=True)
        rel = f"{tut}/{src.stem}"
        if kind == "image":
            dst = out_dir / src.name
            shutil.copy2(src, dst)
            self.used.add(dst)
            return (f"/docs/media/{tut}/{src.name}", None, kind)
        trim = item.get("trim")
        digest = sha256(src)
        key = f"{digest}:{ENC_KEY}:{trim}"
        mp4, jpg = out_dir / f"{src.stem}.mp4", out_dir / f"{src.stem}.jpg"
        self.used.update([mp4, jpg])
        if self.cache.get(rel) != key or not mp4.exists() or not jpg.exists():
            print(f"  encoding {rel}")
            vf = [f"scale=-2:'min({ENC['max_height']},ih)':flags=lanczos", "format=yuv420p"]
            pre = []
            if trim:
                first, last = trim
                sel = f"gte(n\\,{max(first, 1) - 1})" + (f"*lte(n\\,{last - 1})" if last else "")
                vf.insert(0, f"select='{sel}',setpts=N/FRAME_RATE/TB")
            subprocess.run([self.ffmpeg, "-v", "error", "-y", *pre, "-i", str(src), "-an",
                            "-vf", ",".join(vf), "-c:v", "libx264", "-profile:v", "high",
                            "-preset", ENC["preset"], "-crf", str(ENC["crf"]),
                            "-movflags", "+faststart", str(mp4)], check=True)
            # the still: the clip's last frame, which shows what the gesture did
            subprocess.run([self.ffmpeg, "-v", "error", "-y", "-sseof", "-0.15", "-i", str(mp4),
                            "-frames:v", "1", "-q:v", "5", str(jpg)], check=True)
            self.cache[rel] = key
        return (f"/docs/media/{tut}/{src.stem}.mp4", f"/docs/media/{tut}/{src.stem}.jpg", kind)

    def finish(self):
        for f in (DOCS / "media").rglob("*"):
            if f.is_file() and f != self.cache_file and f not in self.used:
                f.unlink()
                print(f"  removed {f.relative_to(SITE)}")
        live = {f"{p.parent.name}/{p.stem}" for p in self.used}
        self.cache = {k: v for k, v in sorted(self.cache.items()) if k in live}
        self.cache_file.write_text(json.dumps(self.cache, indent=1) + "\n")


def video_tag(src, poster, label, loop=True):
    return (f'<video class="clip-video" muted playsinline{" loop" if loop else ""} preload="none" controls '
            f'width="720" height="1280" data-poster="{poster}" aria-label="{esc(label)}">'
            f'<source src="{src}" type="video/mp4"></video>')


def media_figure(m, item, label_for_a11y, caption_html):
    src, poster, kind = m
    if kind == "image":
        inner = f'<img class="clip-video" src="{src}" alt="{esc(label_for_a11y)}" loading="lazy">'
    else:
        inner = video_tag(src, poster, label_for_a11y, loop=not item.get("hold"))
    watch = item.get("watch")
    if watch and watch.startswith("https://"):
        caption_html += f' · <a href="{esc(watch)}">Watch on YouTube</a>'
    return f'<figure class="clip">{inner}<figcaption>{caption_html}</figcaption></figure>'


# ---------------------------------------------------------------- tutorials

def load_tutorials(source):
    tuts = []
    root = source / "tutorials"
    for f in sorted(root.glob("*/tutorial.json")):
        folder = f.parent.name
        if folder[0] in "_.":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            fail(f"{f}: {e}")
        if not data.get("title") or not data.get("steps"):
            warn(f"{folder}/tutorial.json has no title or no steps: left out")
            continue
        data["_folder"] = folder
        data["_slug"] = url_slug(folder)
        tuts.append(data)
    for d in root.iterdir():
        if d.is_dir() and d.name[0] not in "_." and not (d / "tutorial.json").exists():
            warn(f"tutorials/{d.name}/ has no tutorial.json (left over?)")
    # Kneady's own menu order: by order, then title; numbered from 0 when the first has order 0
    tuts.sort(key=lambda t: (t.get("order", 999), t["title"].lower()))
    base = 0 if tuts and tuts[0].get("order") == 0 else 1
    for i, t in enumerate(tuts):
        t["_number"] = base + i
        if not t.get("summary"):
            warn(f"{t['_folder']}: no summary (its menu tooltip is empty too)")
    return tuts


def clip_index(tuts):
    """'folder/stem' -> (tutorial, step number from 1, media item)"""
    idx = {}
    for t in tuts:
        for n, step in enumerate(t["steps"], 1):
            for item in step.get("media") or []:
                idx[f"{t['_folder']}/{Path(item['file']).stem}"] = (t, n, item)
    return idx


# ---------------------------------------------------------------- markdown pages

def render_markdown(md_text, page_key, source, media, clips, tuts):
    md = MarkdownIt("commonmark").enable("table")
    soup = BeautifulSoup(f'<div class="prose">{md.render(md_text)}</div>', "html.parser")
    prose = soup.div

    # heading ids, as GitHub makes them
    seen = {}
    for h in prose.find_all(["h1", "h2", "h3", "h4"]):
        base = slugify(h.get_text())
        n = seen.get(base, 0)
        seen[base] = n + 1
        h["id"] = base if n == 0 else f"{base}-{n}"

    # links between the docs, and images
    for a in prose.find_all("a", href=True):
        href = a["href"]
        m = re.match(r"^(?:\./|docs/)?(GUIDE|TUTORIALS)\.md(#.*)?$", href)
        if m:
            a["href"] = ("/docs/guide/" if m.group(1) == "GUIDE" else "/docs/writing-a-tutorial/") + (m.group(2) or "")
        elif href.endswith(".md") or ".md#" in href:
            warn(f"{page_key}: link to {href} has no page on the site; left as text")
            a.unwrap()
    for img in prose.find_all("img", src=True):
        src = img["src"]
        if re.match(r"^[a-z]+:", src):
            continue
        f = (source / "docs" / src).resolve()
        if f.exists():
            dst = DOCS / "images" / f.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            img["src"] = f"/docs/images/{f.name}"
            img["loading"] = "lazy"
        else:
            warn(f"{page_key}: image {src} not found")

    # wide things scroll on their own on a phone
    for t in prose.find_all(["table", "pre"]):
        wrap = soup.new_tag("div", attrs={"class": "scroll-x", "tabindex": "0", "role": "region",
                                          "aria-label": "Table" if t.name == "table" else "Code"})
        t.wrap(wrap)

    # Pro-only
    for prefix in CONFIG["pro_only"].get(page_key, []):
        hits = [el for el in prose.find_all(["p", "li"]) if norm(el).startswith(prefix)]
        if not hits:
            fail(f"{page_key}: pro_only text '{prefix}' not found")
        for el in hits:
            el["class"] = el.get("class", []) + ["pro-only"]
            badge = soup.new_tag("span", attrs={"class": "badge-pro"})
            badge.string = "Pro"
            el.insert(0, " ")
            el.insert(0, badge)

    # tutorial clips, where the config puts them
    for entry in clips:
        heading = prose.find(id=entry["section"])
        if not heading:
            fail(f"{page_key}: section '{entry['section']}' not found (heading renamed?) - fix tools/docs_config.json")
        section = []  # the blocks under this heading, up to the next heading of any level
        for sib in heading.find_next_siblings():
            if re.match(r"^h[1-6]$", sib.name or ""):
                break
            section.append(sib)
        figs = []
        for ref in entry["clips"]:
            hit = CLIPS.get(ref)
            if not hit:
                fail(f"{page_key}: clip '{ref}' is in no tutorial - fix tools/docs_config.json")
            t, n, item = hit
            m = media.clip(t["_folder"], item)
            if not m:
                continue
            step_title = t["steps"][n - 1].get("title", f"Step {n}")
            short = re.sub(r"^Step \d+:\s*", "", step_title)
            cap = (f'<strong>{esc(short)}</strong>'
                   f'<span>From tutorial {t["_number"]}, {esc(t["title"])}</span>')
            figs.append(media_figure(m, item, f"{t['title']}, {step_title}", cap))
        block = BeautifulSoup(f'<div class="doc-clips"><p class="kicker">Examples</p>'
                              f'<div class="clip-row">{"".join(figs)}</div></div>', "html.parser").div
        if "after" in entry:
            want = entry["after"]
            target = next((el for el in section if norm(el).startswith(want)), None)
            if target is None:
                for el in section:
                    target = next((x for x in el.find_all(["li", "p"])
                                   if norm(x).startswith(want)), None)
                    if target:
                        break
            if target is None:
                fail(f"{page_key}: in '{entry['section']}', no text starts with '{want}' - fix tools/docs_config.json")
            if target.name == "li":
                target.append(block)
            else:
                target.insert_after(block)
        else:
            (section[-1] if section else heading).insert_after(block)

    toc = [(h.name, h["id"], h.get_text()) for h in prose.find_all(["h2", "h3"])]
    title_el = prose.find("h1")
    title = title_el.get_text() if title_el else page_key
    if title_el:
        title_el.extract()
    return title, str(prose), toc


def toc_html(toc, label):
    groups = []  # (h2 id, text, [(h3 id, text)])
    for level, hid, text in toc:
        if level == "h2" or not groups:
            groups.append((hid, text, []))
        else:
            groups[-1][2].append((hid, text))
    items = []
    for hid, text, subs in groups:
        sub = "".join(f'<li><a href="#{s}">{esc(t)}</a></li>' for s, t in subs)
        items.append(f'<li><a href="#{hid}">{esc(text)}</a>{f"<ol>{sub}</ol>" if sub else ""}</li>')
    return (f'<nav class="toc" aria-label="{esc(label)}: contents"><p class="kicker">On this page</p>'
            f'<ol>{"".join(items)}</ol></nav>')


def build_markdown_page(shell, source, media, tuts, md_name, page_key, slug, description, crumb, lede):
    path = source / "docs" / md_name
    if not path.exists():
        fail(f"{path} not found")
    title, body, toc = render_markdown(path.read_text(encoding="utf-8"), page_key, source, media,
                                       CONFIG["clips"].get(page_key, []), tuts)
    html_body = (f'<header class="doc-head"><h1>{esc(crumb)}</h1><p class="lede">{lede}</p></header>'
                 f'<div class="doc-layout">{toc_html(toc, crumb)}<article class="doc-article">{body}</article></div>')
    out = DOCS / slug / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page_html(shell, crumb, description, html_body,
                             [("Support", "/support.html"), ("Docs", "/docs/"), (crumb, None)]), encoding="utf-8")
    return toc


# ---------------------------------------------------------------- index

def build_index(shell, tuts, guide_toc, version):
    ver = f"Kneady Controls {esc(version)}" if version else "Kneady Controls"
    g = "".join(f'<li><a href="/docs/guide/#{hid}">{esc(text)}</a></li>'
                for level, hid, text in guide_toc if level == "h2")
    rows = "".join(
        f'<li><span class="num">{t["_number"]}</span>'
        f'<span class="t-title">{esc(t["title"])}</span>'
        f'<span class="t-sum">{esc(t.get("summary") or "")}</span></li>' for t in tuts)
    body = f"""<header class="doc-head">
<h1>Kneady Controls docs</h1>
<p class="lede">The Kneady Controls guide, the tutorials that play inside Blender, and how to write tutorials of your own.</p>
<p class="edition">For {ver}, the free version on extensions.blender.org. Anything that needs <strong>Kneady Controls Pro</strong> is marked <span class="badge-pro">Pro</span>.</p>
</header>
<div class="doc-index">
  <div class="band">
    <h2 id="guide"><a href="/docs/guide/">Guide</a></h2>
    <p>How each part of Kneady works, with clips from the tutorials as examples.</p>
    <ol class="guide-list">{g}</ol>
  </div>
  <div>
    <h2 id="tutorials">Tutorials in Kneady</h2>
    <p>These tutorials play inside Blender. When <strong>Help</strong> is set to <strong>Learn</strong> (the default), they are listed under <strong>Start a Tutorial</strong> at the top of the Kneady tab. Each one plays in a panel next to the view, in its own practice scene, and checks off each step as you complete it. The guide uses their clips as examples. See <a href="/docs/guide/#tutorials">Tutorials</a> in the guide.</p>
    <ol class="tut-list">{rows}</ol>
  </div>
  <div class="band">
    <h2 id="writing"><a href="/docs/writing-a-tutorial/">Writing a tutorial</a></h2>
    <p>For add-on developers, riggers and character sellers. You can write tutorials in the Kneady tab, include them with an add-on, or attach them to a rig so they are saved in its file.</p>
  </div>
</div>
<p class="fineprint">The tutorials' clips and practice scenes are public domain (CC0 1.0): use them for anything. Questions go to the <a href="https://discord.gg/cDD3acK6bM">Space Squirrel Discord</a>.</p>"""
    (DOCS / "index.html").write_text(page_html(shell, "Docs", "Kneady Controls guide and tutorials.", body,
                                               [("Support", "/support.html"), ("Docs", None)]), encoding="utf-8")


# ---------------------------------------------------------------- main

CLIPS = {}


def main():
    global CLIPS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, help="a copy of the Kneady repository (needs docs/ and tutorials/)")
    args = ap.parse_args()
    source = Path(args.source).expanduser().resolve()
    for need in ("docs/GUIDE.md", "docs/TUTORIALS.md", "tutorials"):
        if not (source / need).exists():
            fail(f"{source} has no {need}. Point --source at the Kneady folder.")

    version = ""
    manifest = source / "blender_manifest.toml"
    if manifest.exists():
        m = re.search(r'^version\s*=\s*"([^"]+)"', manifest.read_text(encoding="utf-8"), re.M)
        version = m.group(1) if m else ""

    shell = site_shell()
    print(f"Building docs from {source} (Kneady {version or '?'}), cache-bust ?v={shell[0]}")

    # generated folders are made again from scratch; media keeps its encoded clips
    for sub in ("tutorials", "guide", "writing-a-tutorial", "scenes", "images"):  # tutorials/, scenes/: from earlier builds
        if (DOCS / sub).exists():
            shutil.rmtree(DOCS / sub)
    DOCS.mkdir(exist_ok=True)

    media = Media(source)
    tuts = load_tutorials(source)
    CLIPS = clip_index(tuts)
    guide_toc = build_markdown_page(
        shell, source, media, tuts, "GUIDE.md", "guide", "guide",
        "The Kneady Controls guide: regions, buttons, commands, dragging, posing, menus, 3D handles and more.",
        "Guide", "How each part of Kneady works, with clips from the tutorials next to the parts they show.")
    build_markdown_page(
        shell, source, media, tuts, "TUTORIALS.md", "writing", "writing-a-tutorial",
        "How to write a Kneady tutorial: in the Kneady tab, or as tutorial.json by hand.",
        "Writing a tutorial", "For add-on developers, riggers and character sellers. A Kneady tutorial is a folder with a tutorial.json file, its clips and a practice scene.")
    build_index(shell, tuts, guide_toc, version)
    media.finish()
    print(f"Done: {len(tuts)} tutorials, guide, writing a tutorial.")
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings:
            print("  - " + w)


if __name__ == "__main__":
    main()
