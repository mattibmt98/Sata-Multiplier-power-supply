"""Minimal KiCad 9 schematic emitter: symbol library access + placement/wiring.

Exists because SKiDL's force-directed placer stacks symbols on top of each
other (it placed R_EN and C_BUCK_IN at the identical coordinate) and emits the
KiCad 7 file format with a project name that does not match the .kicad_pro,
which leaves every symbol's instance data unresolvable in KiCad 9.

This module does no placement thinking of its own -- layout is spelled out
explicitly in gen_sch.py. All it does is resolve pin geometry from the real
KiCad libraries so wires provably land on pins.
"""
import os, re, uuid as _uuid

LIBDIR = r"D:\Kicad\share\kicad\symbols"
GRID = 1.27
NS = _uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def uid(*parts):
    """Deterministic UUID, so regenerating does not churn the whole file."""
    return str(_uuid.uuid5(NS, "|".join(str(p) for p in parts)))


# --------------------------------------------------------------- s-expr parse
def parse(text):
    toks = re.findall('\\(|\\)|"(?:[^"\\\\]|\\\\.)*"|[^\\s()]+', text)
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
            cur.append(t[1:-1] if t.startswith('"') else t)
    return cur[0] if cur else []


def find_all(node, tag):
    return [n for n in node if isinstance(n, list) and n and n[0] == tag]


def find(node, tag):
    r = find_all(node, tag)
    return r[0] if r else None


# --------------------------------------------------------------- library
_libcache = {}
# Project-local symbol libraries, keyed by the nickname used in a lib_id.
SYMBOL_LIBS = {"sata_psu": "libs/sata_psu.kicad_sym"}


def _libpath(lib):
    if lib in SYMBOL_LIBS:
        return SYMBOL_LIBS[lib]
    return os.path.join(LIBDIR, lib + ".kicad_sym")


def _libtext(lib, refresh=False):
    if refresh:
        _libcache.pop(lib, None)
    if lib not in _libcache:
        with open(_libpath(lib), encoding="utf-8") as f:
            _libcache[lib] = f.read()
    return _libcache[lib]


def raw_block(lib, name):
    """Raw s-expression text of one top-level symbol, by paren balance."""
    t = _libtext(lib)
    m = re.search(r'\n\t\(symbol "' + re.escape(name) + r'"', t)
    if not m:
        raise KeyError(f"{lib}:{name} not found")
    i = m.start() + 1
    depth = 0
    for j in range(i, len(t)):
        if t[j] == '(':
            depth += 1
        elif t[j] == ')':
            depth -= 1
            if depth == 0:
                return t[i:j + 1]
    raise ValueError("unbalanced")


class SymDef:
    """A resolved library symbol: pin geometry + text to embed in lib_symbols."""

    def __init__(self, lib, name):
        self.lib, self.name = lib, name
        self.lib_id = f"{lib}:{name}"
        block = raw_block(lib, name)
        tree = parse(block)
        ext = find(tree, "extends")
        if ext:
            parent = ext[1]
            pblock = raw_block(lib, parent)
            # Flatten: parent graphics/pins, renamed to this symbol.
            block = pblock.replace(f'"{parent}_', f'"{name}_')
            block = re.sub(r'\(symbol "' + re.escape(parent) + r'"',
                           f'(symbol "{name}"', block, count=1)
            block = re.sub(r'\(property "Value" "[^"]*"',
                           f'(property "Value" "{name}"', block, count=1)
            tree = parse(block)
        self.block = re.sub(r'\(symbol "' + re.escape(name) + r'"',
                            f'(symbol "{self.lib_id}"', block, count=1)
        self.pins = {}
        self._collect_pins(tree)

    def _collect_pins(self, node):
        for child in node:
            if not isinstance(child, list) or not child:
                continue
            if child[0] == "pin" and find(child, "at"):
                at = find(child, "at")
                num = find(child, "number")
                nm = find(child, "name")
                x, y = float(at[1]), float(at[2])
                if num:
                    self.pins[num[1]] = (x, y)
                if nm and nm[1] not in ("~", ""):
                    self.pins.setdefault(nm[1], (x, y))
            else:
                self._collect_pins(child)


_symcache = {}


def symdef(lib_id):
    if lib_id not in _symcache:
        lib, name = lib_id.split(":", 1)
        _symcache[lib_id] = SymDef(lib, name)
    return _symcache[lib_id]


# --------------------------------------------------------------- placement
def _rot(px, py, rot):
    """Symbol-local (Y-up) pin offset -> schematic (Y-down) offset."""
    if rot == 0:
        return px, -py
    if rot == 90:
        return -py, -px
    if rot == 180:
        return -px, py
    if rot == 270:
        return py, px
    raise ValueError(f"bad rotation {rot}")


def ongrid(v):
    return abs(round(v / GRID) - v / GRID) < 1e-6


class Comp:
    def __init__(self, lib_id, ref, value, x, y, rot, footprint, sheet):
        self.d = symdef(lib_id)
        self.lib_id, self.ref, self.value = lib_id, ref, value
        self.x, self.y, self.rot = float(x), float(y), rot
        self.footprint = footprint
        self.uuid = uid(sheet.name, ref)
        for n, v in (("x", self.x), ("y", self.y)):
            if not ongrid(v):
                raise ValueError(f"{ref}: {n}={v} off the {GRID}mm grid")

    def pin(self, key):
        px, py = self.d.pins[key]
        dx, dy = _rot(px, py, self.rot)
        p = (round(self.x + dx, 4), round(self.y + dy, 4))
        if not (ongrid(p[0]) and ongrid(p[1])):
            raise ValueError(f"{self.ref}.{key} lands off-grid at {p}")
        return p


class Sheet:
    def __init__(self, name, title, project, paper="A4", index=1):
        self.name, self.title, self.project, self.paper = name, title, project, paper
        # Power-symbol refs must be unique across the whole hierarchy, not just
        # within a page, or KiCad reports duplicate annotation.
        self.index = index
        self.uuid = uid("sheetfile", name)
        self.comps, self.wires, self.juncs = [], [], []
        self.glabels, self.texts = [], []

    def place(self, lib_id, ref, value, x, y, rot=0, footprint="", fields="auto",
              mpn="", dkpn=""):
        check_footprint(footprint)
        c = Comp(lib_id, ref, value, x, y, rot, footprint, self)
        c.fields = fields
        c.mpn, c.dkpn = mpn, dkpn
        self.comps.append(c)
        return c

    def gnd(self, x, y):
        return self.place("power:GND", f"#PWR{self.index:02d}{len(self.comps):02d}", "GND", x, y)

    def flag(self, x, y):
        return self.place("power:PWR_FLAG", f"#FLG{self.index:02d}{len(self.comps):02d}",
                          "PWR_FLAG", x, y)

    def wire(self, *pts):
        for a, b in zip(pts, pts[1:]):
            if abs(a[0] - b[0]) > 1e-6 and abs(a[1] - b[1]) > 1e-6:
                raise ValueError(f"{self.name}: diagonal wire {a}->{b}")
            if a != b:
                self.wires.append((a, b))

    def junction(self, *pts):
        self.juncs.extend(pts)

    def glabel(self, name, x, y, rot=0, shape="bidirectional"):
        self.glabels.append((name, x, y, rot, shape))

    def text(self, s, x, y, size=2.0):
        self.texts.append((s, x, y, size))


# --------------------------------------------------------------- rendering
def _eff(size=1.27, justify=None, hide=False):
    s = f"(effects (font (size {size} {size}))"
    if justify:
        s += f" (justify {justify})"
    if hide:
        s += " (hide yes)"
    return s + ")"


def _prop(name, value, x, y, rot=0, hide=False, justify=None, size=1.27):
    return (f'    (property "{name}" "{value}" (at {x} {y} {rot}) '
            f'{_eff(size, justify, hide)})')


class SheetRef:
    """A (sheet ...) box on the root page pointing at a sub-sheet file."""

    def __init__(self, sub, x, y, w, h, page):
        self.sub, self.x, self.y, self.w, self.h, self.page = sub, x, y, w, h, page
        self.uuid = uid("sheetobj", sub.name)


FOOTPRINT_DIR = "D:/Kicad/share/kicad/footprints"
# Project-local libraries, keyed by the nickname used in a lib_id.
FOOTPRINT_LIBS = {"digikey-footprints": "libs/digikey/digikey-footprints.pretty"}


def check_footprint(fp):
    """Fail loudly on a footprint that does not exist.

    A mistyped footprint is invisible in the schematic and only surfaces when
    the netlist reaches the PCB, so resolve every one at generation time.
    """
    if not fp:
        return
    if ":" not in fp:
        raise ValueError("footprint %r must be LIBRARY:NAME" % fp)
    lib, name = fp.split(":", 1)
    if lib in FOOTPRINT_LIBS:
        path = os.path.join(FOOTPRINT_LIBS[lib], name + ".kicad_mod")
    else:
        path = os.path.join(FOOTPRINT_DIR, lib + ".pretty", name + ".kicad_mod")
    if not os.path.exists(path):
        raise ValueError("footprint not found: %s -> %s" % (fp, path))


def sym_bbox(sd):
    """Approximate symbol-local bounding box from its graphic primitives."""
    xs, ys = [], []
    for m in re.finditer(r"\(xy ([-\d.]+) ([-\d.]+)\)", sd.block):
        xs.append(float(m.group(1))); ys.append(float(m.group(2)))
    for m in re.finditer(r"\((?:start|end|center|mid) ([-\d.]+) ([-\d.]+)\)", sd.block):
        xs.append(float(m.group(1))); ys.append(float(m.group(2)))
    for x, y in sd.pins.values():
        xs.append(x); ys.append(y)
    if not xs:
        return (-1.27, -1.27, 1.27, 1.27)
    return (min(xs), min(ys), max(xs), max(ys))


def placed_bbox(lib_id, x, y, rot):
    x0, y0, x1, y1 = sym_bbox(symdef(lib_id))
    corners = [_rot(cx, cy, rot) for cx in (x0, x1) for cy in (y0, y1)]
    dxs = [c[0] for c in corners]; dys = [c[1] for c in corners]
    return (x + min(dxs), y + min(dys), x + max(dxs), y + max(dys))


def field_positions(c, side="auto"):
    """Where to hang Reference and Value so they clear the body and its wires.

    KiCad composes a property's angle and justification with the symbol's own
    rotation, so anything rotation-specific gets flipped or turned on its side.
    Centred text at a computed offset is orientation-proof.
    """
    bx0, by0, bx1, by1 = placed_bbox(c.lib_id, c.x, c.y, c.rot)
    if side == "left":
        return (bx0 - 7.62, c.y - 1.27), (bx0 - 7.62, c.y + 1.27)
    if side == "above":
        return (c.x, by0 - 5.08), (c.x, by0 - 2.54)
    if (by1 - by0) >= (bx1 - bx0):
        # Tall part: wires leave top and bottom, so put text beside it.
        return (bx1 + 7.62, c.y - 1.27), (bx1 + 7.62, c.y + 1.27)
    # Wide part: wires leave left and right, so put text above and below.
    return (c.x, by0 - 2.54), (c.x, by1 + 2.54)


def _split_at_junctions(sheet):
    """Split any wire that a junction lands on mid-span.

    KiCad binds a T-connection when a wire ENDS at a junction point; a wire
    merely passing through one is not split implicitly. Emitting the segments
    pre-split is what the KiCad editor itself stores, and it makes every
    T-connection unambiguous.
    """
    juncs = set(sheet.juncs)
    changed = True
    while changed:
        changed = False
        out = []
        for (a, b) in sheet.wires:
            hit = None
            for j in juncs:
                if j == a or j == b:
                    continue
                on_v = a[0] == b[0] == j[0] and min(a[1], b[1]) < j[1] < max(a[1], b[1])
                on_h = a[1] == b[1] == j[1] and min(a[0], b[0]) < j[0] < max(a[0], b[0])
                if on_v or on_h:
                    hit = j
                    break
            if hit:
                out.append((a, hit))
                out.append((hit, b))
                changed = True
            else:
                out.append((a, b))
        sheet.wires = out


def render(sheet, root_uuid, sheet_obj_uuid=None, sheets=None, page="1"):
    """Emit one .kicad_sch file. sheet_obj_uuid=None means this is the root."""
    _split_at_junctions(sheet)
    L = []
    a = L.append
    a("(kicad_sch")
    a("  (version 20250114)")
    a('  (generator "sata_psu_gen")')
    a('  (generator_version "9.0")')
    a(f'  (uuid "{sheet.uuid}")')
    a(f'  (paper "{sheet.paper}")')
    a("  (title_block")
    a(f'    (title "{sheet.title}")')
    a('    (date "")')
    a('    (company "5-Bay SATA Drive PSU")')
    a("  )")

    # lib_symbols: every distinct symbol used on this page.
    a("  (lib_symbols")
    for lid in sorted({c.lib_id for c in sheet.comps}):
        for line in symdef(lid).block.split("\n"):
            a("    " + line.replace("\t", "  "))
    a("  )")

    for (x1, y1), (x2, y2) in sheet.wires:
        a("  (wire")
        a(f"    (pts (xy {x1} {y1}) (xy {x2} {y2}))")
        a("    (stroke (width 0) (type default))")
        a(f'    (uuid "{uid(sheet.name, "w", x1, y1, x2, y2)}")')
        a("  )")

    for (x, y) in sheet.juncs:
        a("  (junction")
        a(f"    (at {x} {y})")
        a("    (diameter 0) (color 0 0 0 0)")
        a(f'    (uuid "{uid(sheet.name, "j", x, y)}")')
        a("  )")

    for (name, x, y, rot, shape) in sheet.glabels:
        just = "right" if rot == 180 else "left"
        a(f'  (global_label "{name}"')
        a(f"    (shape {shape})")
        a(f"    (at {x} {y} {rot})")
        a("    (fields_autoplaced yes)")
        a(f"    {_eff(1.27, just)}")
        a(f'    (uuid "{uid(sheet.name, "gl", name, x, y)}")')
        a("  )")

    for (s, x, y, size) in sheet.texts:
        a(f'  (text "{s}"')
        a("    (exclude_from_sim no)")
        a(f"    (at {x} {y} 0)")
        a(f"    {_eff(size, 'left bottom')}")
        a(f'    (uuid "{uid(sheet.name, "t", s, x, y)}")')
        a("  )")

    for c in sheet.comps:
        power = c.lib_id.startswith("power:")
        a("  (symbol")
        a(f'    (lib_id "{c.lib_id}")')
        a(f"    (at {c.x} {c.y} {c.rot})")
        a("    (unit 1)")
        a("    (exclude_from_sim no)")
        a(f"    (in_bom {'no' if power else 'yes'})")
        a(f"    (on_board {'no' if power else 'yes'})")
        a("    (dnp no)")
        a("    (fields_autoplaced yes)")
        a(f'    (uuid "{c.uuid}")')
        # Counter-rotate the fields so text stays horizontal whatever the
        # symbol orientation, and centre them so justification cannot flip.
        (rx, ry), (vx, vy) = field_positions(c, getattr(c, "fields", "auto"))
        fang = 90 if c.rot in (90, 270) else 0
        a(_prop("Reference", c.ref, rx, ry, fang, hide=power))
        a(_prop("Value", c.value, vx, vy, fang, hide=power))
        a(_prop("Footprint", c.footprint, c.x, c.y, 0, hide=True))
        a(_prop("Datasheet", "~", c.x, c.y, 0, hide=True))
        if getattr(c, "mpn", ""):
            a(_prop("MPN", c.mpn, c.x, c.y, 0, hide=True))
        if getattr(c, "dkpn", ""):
            a(_prop("DigiKey", c.dkpn, c.x, c.y, 0, hide=True))
        a("    (instances")
        a(f'      (project "{sheet.project}"')
        path = f"/{root_uuid}" if sheet_obj_uuid is None else f"/{root_uuid}/{sheet_obj_uuid}"
        a(f'        (path "{path}"')
        a(f'          (reference "{c.ref}") (unit 1)')
        a("        )")
        a("      )")
        a("    )")
        a("  )")

    for sr in (sheets or []):
        a("  (sheet")
        a(f"    (at {sr.x} {sr.y})")
        a(f"    (size {sr.w} {sr.h})")
        a("    (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)")
        a("    (stroke (width 0.1524) (type solid))")
        a("    (fill (color 0 0 0 0.0000))")
        a(f'    (uuid "{sr.uuid}")')
        a(f'    (property "Sheetname" "{sr.sub.title}" (at {sr.x} {sr.y - 0.7} 0) '
          f"{_eff(1.524, 'left bottom')})")
        a(f'    (property "Sheetfile" "{sr.sub.filename}" (at {sr.x} {sr.y + sr.h + 1.4} 0) '
          f"{_eff(1.524, 'left top')})")
        a("    (instances")
        a(f'      (project "{sheet.project}"')
        a(f'        (path "/{root_uuid}" (page "{sr.page}"))')
        a("      )")
        a("    )")
        a("  )")

    if sheet_obj_uuid is None:
        a("  (sheet_instances")
        a('    (path "/" (page "1"))')
        a("  )")
    a("  (embedded_fonts no)")
    a(")")
    return "\n".join(L) + "\n"
