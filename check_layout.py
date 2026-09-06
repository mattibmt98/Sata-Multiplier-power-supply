"""Verify the generated sheets are actually readable: no overlapping symbols.

The first attempt at this schematic (SKiDL's force-directed placer) put R_EN and
C_BUCK_IN at the identical coordinate, so "ERC passes" is not evidence that a
schematic can be read. This checks the geometry directly.
"""
import re
import glob
import sch_lib as S


def bbox(symdef):
    """Approximate symbol-local bounding box from its graphic primitives."""
    xs, ys = [], []
    for m in re.finditer(r"\(xy ([-\d.]+) ([-\d.]+)\)", symdef.block):
        xs.append(float(m.group(1)))
        ys.append(float(m.group(2)))
    for m in re.finditer(r"\((?:start|end|center|mid) ([-\d.]+) ([-\d.]+)\)", symdef.block):
        xs.append(float(m.group(1)))
        ys.append(float(m.group(2)))
    for x, y in symdef.pins.values():
        xs.append(x)
        ys.append(y)
    if not xs:
        return (-1.27, -1.27, 1.27, 1.27)
    return (min(xs), min(ys), max(xs), max(ys))


def placed_box(lib_id, x, y, rot):
    x0, y0, x1, y1 = bbox(S.symdef(lib_id))
    corners = [S._rot(cx, cy, rot) for cx in (x0, x1) for cy in (y0, y1)]
    dxs = [c[0] for c in corners]
    dys = [c[1] for c in corners]
    return (x + min(dxs), y + min(dys), x + max(dxs), y + max(dys))


def overlap(a, b, margin=0.0):
    return not (a[2] <= b[0] + margin or b[2] <= a[0] + margin
                or a[3] <= b[1] + margin or b[3] <= a[1] + margin)


def main():
    total, problems = 0, 0
    for path in sorted(glob.glob("kicad/sata_psu_*.kicad_sch")):
        text = open(path, encoding="utf-8").read()
        body = text[text.find("  (wire"):] or text
        placed = []
        for m in re.finditer(
                r'\(symbol\n\s+\(lib_id "([^"]+)"\)\n\s+\(at ([-\d.]+) ([-\d.]+) (\d+)\)',
                body):
            lib_id, x, y, rot = m.group(1), float(m.group(2)), float(m.group(3)), int(m.group(4))
            ref = re.search(r'\(reference "([^"]+)"\)', body[m.end():m.end() + 2500])
            placed.append((ref.group(1) if ref else "?", lib_id,
                           placed_box(lib_id, x, y, rot)))
        total += len(placed)
        hits = []
        for i in range(len(placed)):
            for j in range(i + 1, len(placed)):
                if overlap(placed[i][2], placed[j][2]):
                    hits.append((placed[i][0], placed[j][0]))
        name = path.split("sata_psu_")[1].replace(".kicad_sch", "")
        problems += len(hits)
        status = "OK" if not hits else "OVERLAP: " + ", ".join("%s/%s" % h for h in hits)
        if hits:
            print()
            print("     %-10s %s" % (name, status))
    print("%d symbols checked, %d overlapping pairs" % (total, problems))
    return problems


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)
