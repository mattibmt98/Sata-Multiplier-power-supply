"""Place every part of the 5-bay SATA PSU on the smallest sensible board.

Same rule as gen_sch.py: every coordinate here is deliberate, and pcb_lib does
no placement thinking of its own. Coordinates are board-local -- (0, 0) is the
top-left corner of the outline -- and get the ORIGIN offset only on emit.

Layout, top to bottom, follows the power:

  band 1   J8 -> F8 -> Q8, the 5.1 A input path, straight and short along the
           top edge. The barrel jack's body front sits exactly on the outline
           so the plug is not blocked by board material.
  band 2   bulk (C81, C82, C83) then the whole 5 V buck, left to right.
  band 3   five identical channel cells side by side, each one column wide,
           output header at the bottom edge. Cells are generated from one
           function, so all five are identical by construction.

Board area is not fixed: the outline is fitted to the placement afterwards.
"""
import os
import pcb_lib as P

NET = "kicad/from_geometry.net"
OUT = "kicad/sata_psu.kicad_pcb"
ORIGIN = (30.0, 30.0)      # board top-left in KiCad page space
MARGIN = 1.0               # courtyard-to-outline
CORNER = 2.0               # outline corner radius

places = []


def put(ref, x, y, rot=0, ref_at=None, ref_rot=0):
    """Place one part. ref_at aims its silkscreen reference, in board space and
    relative to the footprint origin -- see channel() for which gap each of the
    tight ones is aimed at."""
    places.append(P.Placement(ref, x, y, rot, ref_at=ref_at, ref_rot=ref_rot))


# ------------------------------------------------------- band 1: input path
# J8 body front is at local y = -1, so y = 1.0 puts it on the outline edge.
put("J8", 9.0, 1.5, ref_at=(0, 3.0))                 # barrel jack, opening faces -y (top edge)
put("F8", 18.0, 5.5, ref_at=(8.9, -2.6))                # 5x20 clips; pad1 <- jack, pad2 -> Q8
put("Q8", 45.0, 7.0, ref_at=(-1.0, -4.4))                # TO-252 guard, leads on its left
put("C83", 54.5, 4.0, ref_at=(0, -2.0))               # 10uF HF right at Q8's source

# ------------------------------------------------------- band 2: bulk + buck
put("C81", 5.75, 20.5, ref_at=(0.6, -3.2))              # radial: origin is pad 1, body straddles it
put("C82", 16.75, 20.5, ref_at=(0.6, -3.2))

BX, BY = 40.0, 20.5                 # buck anchor = U9
put("U9", BX, BY, ref_at=(0, 2.6))                   # 1 GND  2 SW  3 VIN / 4 VFB  5 EN  6 VBST
put("C91", BX - 5.5, BY + 2.4, ref_at=(0, 2.0))      # input caps, close to VIN/GND
put("C92", BX - 5.5, BY - 2.4, ref_at=(0, -2.0))
put("C93", BX - 1.0, BY - 4.6, ref_at=(0, -1.6))      # bootstrap, spans VBST..SW
put("R91", BX + 3.5, BY - 4.6, ref_at=(0, -1.6))      # EN pull-up to 12V
put("L9", BX + 6.0, BY + 2.0, ref_at=(0, 0))       # SW -> 5V_MAIN
put("R92", BX + 12.5, BY - 3.0, 90, ref_at=(2.0, 0))  # feedback divider, 5V at the top
put("R93", BX + 12.5, BY + 0.5, 90, ref_at=(0, 2.5))
put("C94", BX + 16.5, BY + 2.0, ref_at=(0, -2.0))     # 5V output caps
put("C95", BX + 21.5, BY + 2.0, ref_at=(0, -2.0))

# ------------------------------------------------------------ band 3: channels
CW = 12.7                           # one cell = one header pitch
CH_X0 = 1.0                         # left edge of cell 1
CH_Y = 27.5                         # top of the channel band

def channel(n, x0, yt):
    """One channel cell. Rows, top to bottom: gate network, switch, fuse, bulk
    decoupling, output header. Identical for all five channels.

    At this pitch the rows leave no horizontal silk lanes, so most references
    are turned on their side and parked in a vertical sliver between parts.
    The slivers, in cell-local x: 0.0-0.9 and 5.5-7.0 in the gate row,
    4.7-7.1 and 10.9-12.7 in the switch row, 0.0-3.4 in the fuse row, and one
    horizontal lane at cell-local y 19.8-21.2, just above the header. The
    electrolytic's reference goes inside its own can outline. The minus half
    of a KiCad radial-cap silk is solid hatching, so it has to sit in the plus
    half, above pad 1 -- which is the only free space left in that row.
    """
    put("C%d1" % n, x0 + 3.2, yt + 1.4, ref_at=(-2.7, 0), ref_rot=90)
    put("D%d" % n, x0 + 9.3, yt + 1.4, ref_at=(2.9, 0), ref_rot=90)
    put("R%d" % n, x0 + 3.2, yt + 4.6, ref_at=(2.65, 0), ref_rot=90)
    put("Q%d" % n, x0 + 9.0, yt + 4.6, ref_at=(2.8, 0), ref_rot=90)
    put("F%d" % n, x0 + 6.35, yt + 9.0, ref_at=(-4.5, 0))
    put("C%d3" % n, x0 + 11.4, yt + 9.0, 90, ref_at=(-1.5, 0), ref_rot=90)
    put("C%d2" % n, x0 + 4.6, yt + 15.5, ref_at=(0.4, -2.6))
    put("J%d" % n, x0 + 2.54, yt + 23.0, 90, ref_at=(5.0, -2.5))


for n in range(1, 6):
    channel(n, CH_X0 + (n - 1) * CW, CH_Y)


# ------------------------------------------------------------------ emit
def main():
    comps, nets, padnet = P.read_netlist(NET)
    known = {p.ref for p in places}
    missing = sorted(set(comps) - known)
    extra = sorted(known - set(comps))
    if missing or extra:
        raise SystemExit("placement/netlist mismatch: missing %s extra %s"
                         % (missing, extra))

    # Outline: fitted to the placement, except the top edge, which is pinned to
    # y = 0 where J8's courtyard already sits -- board material in front of the
    # jack's face is what would foul the plug, so none is added there.
    boxes = {p.ref: P.courtyard_box(comps[p.ref].footprint, p.x, p.y, p.rot)
             for p in places}
    x0 = min(b[0] for b in boxes.values()) - MARGIN
    y1 = max(b[3] for b in boxes.values()) + MARGIN
    x1 = max(b[2] for b in boxes.values()) + MARGIN
    y0 = 0.0

    ox, oy = ORIGIN
    fps = [P.build_footprint(comps[p.ref].footprint, p,
                             comps[p.ref].value, padnet,
                             (comps[p.ref].path, comps[p.ref].sheetname,
                              comps[p.ref].sheetfile))
           for p in [q.shift(ox, oy) for q in places]]
    edge = P.edge_rect(x0 + ox, y0 + oy, x1 + ox, y1 + oy, CORNER)

    os.makedirs("kicad", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(P.board(nets, fps, edge, "5-Bay SATA Drive Power Supply"))

    w, h = x1 - x0, y1 - y0
    area = sum((b[2] - b[0]) * (b[3] - b[1]) for b in boxes.values())
    print("%d footprints, %d nets -> %s" % (len(fps), len(nets), OUT))
    print("board %.2f x %.2f mm = %.0f mm2  (courtyards %.0f mm2, fill %.0f%%)"
          % (w, h, w * h, area, 100 * area / (w * h)))


if __name__ == "__main__":
    main()
