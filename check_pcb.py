"""Geometry and connectivity checks on the generated board.

Mirrors what verify.py does for the schematic: KiCad's DRC will not run before
the file loads, and a placement can be legal-but-wrong (courtyards crossing,
a pad that silently lost its net) in ways nothing else reports.
"""
import sys
import pcb_lib as P
import gen_pcb as G


def overlaps(comps, places, clearance=0.0):
    boxes = [(p.ref, P.courtyard_box(comps[p.ref].footprint, p.x, p.y, p.rot))
             for p in places]
    bad = []
    for i, (r1, b1) in enumerate(boxes):
        for r2, b2 in boxes[i + 1:]:
            ox = min(b1[2], b2[2]) - max(b1[0], b2[0]) - clearance
            oy = min(b1[3], b2[3]) - max(b1[1], b2[1]) - clearance
            if ox > 1e-6 and oy > 1e-6:
                bad.append((r1, r2, ox, oy))
    return bad


def closest(comps, places, n=8):
    boxes = [(p.ref, P.courtyard_box(comps[p.ref].footprint, p.x, p.y, p.rot))
             for p in places]
    gaps = []
    for i, (r1, b1) in enumerate(boxes):
        for r2, b2 in boxes[i + 1:]:
            dx = max(b1[0] - b2[2], b2[0] - b1[2])
            dy = max(b1[1] - b2[3], b2[1] - b1[3])
            if dx < 0 and dy < 0:
                continue
            gaps.append((max(dx, dy), r1, r2))
    gaps.sort()
    return gaps[:n]


def main():
    comps, nets, padnet = P.read_netlist(G.NET)
    fails = 0

    bad = overlaps(comps, G.places)
    if bad:
        fails += 1
        print("FAIL courtyard overlaps:")
        for r1, r2, ox, oy in bad:
            print("   %-4s / %-4s  by %.2f x %.2f mm" % (r1, r2, ox, oy))
    else:
        print("PASS no courtyard overlaps")

    # Every pad the netlist names must exist in the real footprint, and every
    # placed footprint pad that the netlist nets must be reachable.
    missing = []
    for (ref, pad) in padnet:
        if pad not in P.pads(comps[ref].footprint):
            missing.append("%s pad %s" % (ref, pad))
    if missing:
        fails += 1
        print("FAIL netlist pads with no pad in the footprint: %s" % missing)
    else:
        print("PASS all %d netlist pads exist in their footprint" % len(padnet))

    # The emitted board must carry each of those nets on the pad.
    txt = open(G.OUT, encoding="utf-8").read()
    board = P.parse_raw(txt)
    got = {}
    for fp in P.rfind_all(board, "footprint"):
        ref = [p for p in P.rfind_all(fp, "property")
               if p[1] == P.q("Reference")][0][2].strip('"')
        for pad in P.rfind_all(fp, "pad"):
            n = P.rfind(pad, "net")
            if n:
                got[(ref, pad[1].strip('"'))] = n[2].strip('"')
    want = {k: v.name for k, v in padnet.items()}
    if got != want:
        fails += 1
        print("FAIL board net assignment differs from the netlist:")
        for k in sorted(set(want) | set(got)):
            if want.get(k) != got.get(k):
                print("   %s: netlist %r board %r" % (k, want.get(k), got.get(k)))
    else:
        print("PASS all %d pad-net assignments match the netlist" % len(want))

    # Placement must be inside the outline (the barrel jack overhangs the top
    # edge on purpose -- that is how the plug clears the board).
    edge = [g for g in P.rfind_all(board, "gr_line")]
    xs, ys = [], []
    for g in edge:
        for t in ("start", "end"):
            n = P.rfind(g, t)
            xs.append(float(n[1]))
            ys.append(float(n[2]))
    bx = (min(xs), min(ys), max(xs), max(ys))
    ox, oy = G.ORIGIN
    out = []
    for p in G.places:
        b = P.courtyard_box(comps[p.ref].footprint, p.x + ox, p.y + oy, p.rot)
        if p.ref == "J8":
            continue
        if (b[0] < bx[0] - 1e-6 or b[1] < bx[1] - 1e-6
                or b[2] > bx[2] + 1e-6 or b[3] > bx[3] + 1e-6):
            out.append(p.ref)
    if out:
        fails += 1
        print("FAIL courtyards outside the outline: %s" % out)
    else:
        print("PASS every courtyard inside the outline (J8 overhangs by design)")

    print("\ntightest courtyard gaps:")
    for g, r1, r2 in closest(comps, G.places):
        print("   %-4s / %-4s  %.2f mm" % (r1, r2, g))
    w, h = bx[2] - bx[0], bx[3] - bx[1]
    print("\nboard %.2f x %.2f mm = %.0f mm2" % (w, h, w * h))
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
