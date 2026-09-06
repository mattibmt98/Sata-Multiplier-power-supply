"""Minimal KiCad 9 PCB emitter: footprint geometry + board file writing.

Same philosophy as sch_lib: this module does no placement thinking. It reads
real .kicad_mod files so courtyards are the manufacturer's, not a guess, and
writes a .kicad_pcb whose pads carry the netlist's nets. gen_pcb.py owns every
coordinate.
"""
import os, re, math, uuid as _uuid
from sch_lib import parse, find, find_all, uid

FOOTPRINT_DIR = "D:/Kicad/share/kicad/footprints"
FOOTPRINT_LIBS = {"digikey-footprints": "libs/digikey/digikey-footprints.pretty"}
PCB_VERSION = "20241229"          # KiCad 9 board format


def fp_path(fp):
    lib, name = fp.split(":", 1)
    if lib in FOOTPRINT_LIBS:
        return os.path.join(FOOTPRINT_LIBS[lib], name + ".kicad_mod")
    return os.path.join(FOOTPRINT_DIR, lib + ".pretty", name + ".kicad_mod")


_modcache = {}


def fp_text(fp):
    if fp not in _modcache:
        with open(fp_path(fp), encoding="utf-8") as f:
            _modcache[fp] = f.read()
    return _modcache[fp]


def fp_tree(fp):
    return parse(fp_text(fp))


# ------------------------------------------------------------------ geometry
def _xy(node, tag):
    n = find(node, tag)
    return (float(n[1]), float(n[2])) if n else None


def _seg_pts(node):
    """Points of one graphic item, enough for a bounding box.

    A circle is stored as centre + a point on the rim, so its extent is the
    radius box, not those two points -- reading them as plain points shifts the
    courtyard of every radial part by half its diameter.
    """
    if node[0] in ("fp_circle", "gr_circle"):
        (cx, cy), (ex, ey) = _xy(node, "center"), _xy(node, "end")
        r = math.hypot(ex - cx, ey - cy)
        return [(cx - r, cy - r), (cx + r, cy + r)]
    if node[0] in ("fp_arc", "gr_arc"):
        # Start/mid/end understate the bulge only for arcs > 180 deg, which do
        # not occur on a courtyard layer.
        return [p for p in (_xy(node, "start"), _xy(node, "mid"),
                            _xy(node, "end")) if p]
    pts = [p for p in (_xy(node, "start"), _xy(node, "end"),
                       _xy(node, "center")) if p]
    poly = find(node, "pts")
    if poly:
        pts += [(float(p[1]), float(p[2])) for p in find_all(poly, "xy")]
    return pts


def _layer_of(node):
    n = find(node, "layer")
    return n[1] if n else ""


def courtyard(fp):
    """(xmin, ymin, xmax, ymax) of the F/B.CrtYd graphics, footprint-local."""
    t = fp_tree(fp)
    pts = []
    for node in t:
        if not isinstance(node, list) or not node[0].startswith("fp_"):
            continue
        if _layer_of(node) in ("F.CrtYd", "B.CrtYd"):
            pts += _seg_pts(node)
    if not pts:
        raise ValueError("no courtyard in %s" % fp)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def rot_pt(x, y, rot):
    """KiCad footprint rotation is counter-clockwise in a y-down space."""
    a = math.radians(rot)
    c, s = math.cos(a), math.sin(a)
    return x * c + y * s, -x * s + y * c


def courtyard_box(fp, x, y, rot):
    """Board-space courtyard rectangle of a footprint placed at (x, y, rot)."""
    x0, y0, x1, y1 = courtyard(fp)
    corners = [rot_pt(cx, cy, rot) for cx in (x0, x1) for cy in (y0, y1)]
    xs = [x + c[0] for c in corners]
    ys = [y + c[1] for c in corners]
    return min(xs), min(ys), max(xs), max(ys)


def pads(fp):
    """{pad number: (x, y, angle)} in footprint-local coordinates."""
    out = {}
    for node in fp_tree(fp):
        if isinstance(node, list) and node and node[0] == "pad":
            at = find(node, "at")
            out.setdefault(node[1], (float(at[1]), float(at[2]),
                                     float(at[3]) if len(at) > 3 else 0.0))
    return out


def pad_xy(fp, num, x, y, rot):
    px, py, _ = pads(fp)[num]
    dx, dy = rot_pt(px, py, rot)
    return x + dx, y + dy


# ------------------------------------------------------------------ netlist
class Comp:
    def __init__(self, ref, value, footprint, path="", sheetname="", sheetfile=""):
        self.ref, self.value, self.footprint = ref, value, footprint
        self.path, self.sheetname, self.sheetfile = path, sheetname, sheetfile


class Net:
    def __init__(self, code, name):
        self.code, self.name, self.nodes = int(code), name, []


def read_netlist(path):
    """-> ({ref: Comp}, [Net], {(ref, pad): Net})."""
    with open(path, encoding="utf-8") as f:
        tree = parse(f.read())
    comps = {}
    for c in find_all(find(tree, "components"), "comp"):
        props = {p[1][1]: (p[2][1] if len(p) > 2 and len(p[2]) > 1 else "")
                 for p in find_all(c, "property")}
        sp = find(c, "sheetpath")
        comps[find(c, "ref")[1]] = Comp(
            find(c, "ref")[1], find(c, "value")[1], find(c, "footprint")[1],
            path=find(sp, "tstamps")[1] + find(c, "tstamps")[1],
            sheetname=props.get("Sheetname", ""),
            sheetfile=props.get("Sheetfile", ""))
    nets, padnet = [], {}
    for n in find_all(find(tree, "nets"), "net"):
        net = Net(find(n, "code")[1], find(n, "name")[1])
        for nd in find_all(n, "node"):
            ref, pin = find(nd, "ref")[1], find(nd, "pin")[1]
            net.nodes.append((ref, pin))
            padnet[(ref, pin)] = net
        nets.append(net)
    return comps, nets, padnet


# ------------------------------------------------------- raw s-expr in / out
# The plain parse() in sch_lib drops quoting, which is fine for reading but
# loses information when a footprint has to be written back out. This one keeps
# every token exactly as it was written.
def parse_raw(text):
    B = chr(92)
    pat = '[(]|[)]|"(?:[^"' + B + B + ']|' + B + B + '.)*"|[^ ' + B + 't' + B + 'n()]+'
    toks = re.findall(pat, text)
    stack, cur = [], []
    for t in toks:
        if t == '(':
            new = []
            cur.append(new)
            stack.append(cur)
            cur = new
        elif t == ')':
            cur = stack.pop()
        else:
            cur.append(t)
    return cur[0] if cur else []


def tag(node):
    return node[0] if isinstance(node, list) and node and isinstance(node[0], str) else None


def rfind_all(node, name):
    return [n for n in node if tag(n) == name]


def rfind(node, name):
    r = rfind_all(node, name)
    return r[0] if r else None


def q(s):
    return '"%s"' % str(s).replace("\\", "\\\\").replace('"', '\\"')


def num(v):
    """Trim float noise; KiCad writes plain decimals."""
    s = "%.6f" % float(v)
    s = s.rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def dumps(node, depth=0):
    if isinstance(node, str):
        return node
    pad = "\t" * depth
    head = node[0] if node and isinstance(node[0], str) else ""
    atoms = []
    i = 1
    while i < len(node) and isinstance(node[i], str):
        atoms.append(node[i])
        i += 1
    rest = node[i:]
    line = pad + "(" + head + ("".join(" " + a for a in atoms))
    if not rest:
        return line + ")"
    return (line + "\n"
            + "\n".join(dumps(n, depth + 1) for n in rest)
            + "\n" + pad + ")")


# ------------------------------------------------------------- board writing
LAYERS = """\t(layers
\t\t(0 "F.Cu" signal)
\t\t(2 "B.Cu" signal)
\t\t(9 "F.Adhes" user "F.Adhesive")
\t\t(11 "B.Adhes" user "B.Adhesive")
\t\t(13 "F.Paste" user)
\t\t(15 "B.Paste" user)
\t\t(5 "F.SilkS" user "F.Silkscreen")
\t\t(7 "B.SilkS" user "B.Silkscreen")
\t\t(1 "F.Mask" user)
\t\t(3 "B.Mask" user)
\t\t(17 "Dwgs.User" user "User.Drawings")
\t\t(19 "Cmts.User" user "User.Comments")
\t\t(21 "Eco1.User" user "User.Eco1")
\t\t(23 "Eco2.User" user "User.Eco2")
\t\t(25 "Edge.Cuts" user)
\t\t(27 "Margin" user)
\t\t(31 "F.CrtYd" user "F.Courtyard")
\t\t(29 "B.CrtYd" user "B.Courtyard")
\t\t(35 "F.Fab" user)
\t\t(33 "B.Fab" user)
\t)"""

SETUP = """\t(setup
\t\t(pad_to_mask_clearance 0)
\t\t(allow_soldermask_bridges_in_footprints no)
\t\t(tenting front back)
\t)"""


class Placement:
    """Where one part goes, plus where its silkscreen reference goes.

    ref_at is an offset in BOARD space from the footprint origin, not in the
    footprint's own rotated frame -- on a board this tight the reference has to
    be aimed at a specific gap between neighbours, and reasoning about that in
    a rotated frame is how silk ends up on top of the part next door.
    """

    def __init__(self, ref, x, y, rot=0, side="F", locked=False,
                 ref_at=None, ref_rot=0, ref_size=0.8):
        self.ref, self.x, self.y, self.rot = ref, float(x), float(y), int(rot) % 360
        self.side, self.locked = side, locked
        self.ref_at, self.ref_rot, self.ref_size = ref_at, ref_rot, ref_size

    def shift(self, dx, dy):
        p = Placement(self.ref, self.x + dx, self.y + dy, self.rot, self.side,
                      self.locked, self.ref_at, self.ref_rot, self.ref_size)
        return p


def _set_at(node, x, y, rot):
    at = rfind(node, "at")
    vals = ["at", num(x), num(y)] + ([num(rot)] if rot else [])
    if at:
        node[node.index(at)] = vals
    else:
        node.insert(2, vals)


def _bump_angle(node, rot):
    """Footprint-relative geometry keeps its coordinates; angles are absolute."""
    at = rfind(node, "at")
    if not at:
        return
    a = float(at[3]) if len(at) > 3 and at[3] not in ("unlocked",) else 0.0
    a = (a + rot) % 360
    keep = [t for t in at[4:] if t == "unlocked"]
    at[:] = ["at", at[1], at[2]] + ([num(a)] if a else []) + keep


def _place_ref(node, pl):
    """Aim the reference designator: board-space offset, upright, fixed size."""
    if pl.ref_at is not None:
        # Position is stored in the footprint's own unrotated frame, but the
        # angle is stored absolute -- verified against a KiCad-written board,
        # where a footprint at 90 deg carries its library text offset unchanged
        # and a text angle of 90.
        lx, ly = rot_pt(pl.ref_at[0], pl.ref_at[1], -pl.rot)
        a = pl.ref_rot % 360
        node[node.index(rfind(node, "at"))] = (
            ["at", num(lx), num(ly)] + ([num(a)] if a else []))
    else:
        _bump_angle(node, pl.rot)
    lay = rfind(node, "layer")
    if lay:
        lay[1] = q("F.SilkS" if pl.side == "F" else "B.SilkS")
    eff = rfind(node, "effects")
    if eff and pl.ref_size:
        font = rfind(eff, "font")
        if font:
            font[font.index(rfind(font, "size"))] = [
                "size", num(pl.ref_size), num(pl.ref_size)]
            th = rfind(font, "thickness")
            if th:
                th[1] = num(pl.ref_size * 0.15)


def build_footprint(fp, pl, value, padnet, meta):
    """One board-level (footprint ...) node from a .kicad_mod, placed and netted."""
    t = parse_raw(fp_text(fp))
    name = fp.split(":", 1)[1]
    out = ["footprint", q(fp)]
    drop = ("version", "generator", "generator_version", "at", "layer", "uuid")
    layer = "F.Cu" if pl.side == "F" else "B.Cu"
    out += [["layer", q(layer)], ["uuid", q(uid("fp", pl.ref))]]
    if pl.locked:
        out.append(["locked", "yes"])
    body = [n for n in t[2:] if tag(n) not in drop]

    for n in body:
        if tag(n) == "property":
            if n[1] == q("Reference"):
                n[2] = q(pl.ref)
                _place_ref(n, pl)
            elif n[1] == q("Value"):
                n[2] = q(value)
                _bump_angle(n, pl.rot)
            else:
                _bump_angle(n, pl.rot)
            n.append(["uuid", q(uid("prop", pl.ref, n[1]))])
        elif tag(n) in ("fp_text",):
            _bump_angle(n, pl.rot)
        elif tag(n) == "pad":
            _bump_angle(n, pl.rot)
            net = padnet.get((pl.ref, n[1].strip('"')))
            if net is not None:
                n.append(["net", str(net.code), q(net.name)])
            n.append(["uuid", q(uid("pad", pl.ref, n[1]))])
        if tag(n) in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly",
                      "fp_text", "fp_text_box", "zone", "model"):
            if tag(n) != "model" and not rfind(n, "uuid"):
                n.append(["uuid", q(uid("g", pl.ref, len(out)))])
        out.append(n)

    _set_at(out, pl.x, pl.y, pl.rot)
    path, sheetname, sheetfile = meta
    if path:
        out += [["path", q(path)], ["sheetname", q(sheetname)],
                ["sheetfile", q(sheetfile)]]
    return out


def edge_rect(x0, y0, x1, y1, r=0.0, width=0.1):
    """Board outline: a rectangle, optionally with rounded corners."""
    segs = []
    if r <= 0:
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        for a, b in zip(pts, pts[1:]):
            segs.append(_gr_line(a, b, width))
        return segs
    for a, b in (((x0 + r, y0), (x1 - r, y0)), ((x1, y0 + r), (x1, y1 - r)),
                 ((x1 - r, y1), (x0 + r, y1)), ((x0, y1 - r), (x0, y0 + r))):
        segs.append(_gr_line(a, b, width))
    for cx, cy, a0 in ((x0 + r, y0 + r, 180), (x1 - r, y0 + r, 270),
                       (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90)):
        segs.append(_gr_arc(cx, cy, r, a0, width))
    return segs


def _gr_line(a, b, width):
    return ["gr_line", ["start", num(a[0]), num(a[1])], ["end", num(b[0]), num(b[1])],
            ["stroke", ["width", num(width)], ["type", "solid"]],
            ["layer", q("Edge.Cuts")], ["uuid", q(uid("edge", a, b))]]


def _gr_arc(cx, cy, r, a0, width):
    p = lambda a: (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
    s, m, e = p(a0), p(a0 + 45), p(a0 + 90)
    return ["gr_arc", ["start", num(s[0]), num(s[1])], ["mid", num(m[0]), num(m[1])],
            ["end", num(e[0]), num(e[1])],
            ["stroke", ["width", num(width)], ["type", "solid"]],
            ["layer", q("Edge.Cuts")], ["uuid", q(uid("arc", cx, cy, a0))]]


def board(nets, footprints, graphics, title=""):
    parts = ["(kicad_pcb",
             "\t(version %s)" % PCB_VERSION,
             '\t(generator "gen_pcb")',
             '\t(generator_version "9.0")',
             "\t(general\n\t\t(thickness 1.6)\n\t\t(legacy_teardrops no)\n\t)",
             '\t(paper "A4")']
    if title:
        parts.append("\t(title_block\n\t\t(title %s)\n\t)" % q(title))
    parts += [LAYERS, SETUP, '\t(net 0 "")']
    for n in nets:
        parts.append("\t(net %d %s)" % (n.code, q(n.name)))
    for f in footprints:
        parts.append(dumps(f, 1))
    for g in graphics:
        parts.append(dumps(g, 1))
    parts.append("\t(embedded_fonts no)")
    parts.append(")")
    return "\n".join(parts) + "\n"
