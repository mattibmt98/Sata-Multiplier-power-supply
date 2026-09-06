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
# J8 body front is at local y = -1, so y = 1.5 puts it on the outline edge.
put("J8", 9.0, 1.5, ref_at=(0, 3.0))                 # barrel jack, opening faces -y (top edge)
put("F8", 18.0, 5.5, ref_at=(8.9, -2.6))                # 5x20 clips; pad1 <- jack, pad2 -> Q8
put("Q8", 45.0, 7.0, ref_at=(-1.0, -4.4))                # TO-252 guard, leads on its left
put("C83", 54.5, 4.0, ref_at=(0, -2.0))               # 10uF HF right at Q8's source
# 12V indicator, on the far side of C83 so it sits on the 12V_MAIN node itself
# -- i.e. downstream of Q8, which is what makes it prove the guard conducts.
put("D81", 59.0, 4.0, 90, ref_at=(0, 2.4))
put("R81", 61.8, 4.0, 90, ref_at=(0, 2.4))

# ------------------------------------------------------- band 2: bulk
# The board-wide buck is gone -- it moved into the channel cells -- so this
# band is now just the input bulk, and the space to its right is free.
put("C81", 5.75, 20.5, ref_at=(0.6, -3.2))              # radial: origin is pad 1, body straddles it
put("C82", 16.75, 20.5, ref_at=(0.6, -3.2))

# --------------------------------------------------- band 2b: the 5V rail links
# R61..R64 sit ON the boundary between the cells they join, so a link is
# physically between its two ports and the sharing is visible on the board.
# 1206, not 0603: see FP_R1206 in gen_sch.py.
LINK_Y = 28.5

# ------------------------------------------------------------ band 3: channels
CW = 12.7                           # one cell = one header pitch
CH_X0 = 1.0                         # left edge of cell 1
CH_Y = 31.0                         # top of the channel band
CB = 19.2                           # switch half starts this far down the cell


def channel(n, x0, yt):
    """One channel cell, now in two halves.

    Top half (yt+0 .. yt+18.7), the port's own buck. Rows are spaced to leave
    two horizontal SILK LANES, because at this pitch a reference has nowhere
    else to go -- the first attempt packed the rows tight and DRC returned 17
    silkscreen violations:

      row A   y 0.3-3.7    C_n5, U_n, C_n6       input HF / regulator / bootstrap
      lane 1  y 3.7-5.1                          refs for row A
      row B   y 4.8-7.8    C_n4, R_n4, R_n2, R_n3   input bulk, EN, feedback
      lane 2  y 7.8-9.2                          refs for row B
      row C   y 9.2-18.7   L_n, and C_n7/C_n8 stacked to its right

    plus two vertical slivers in row C: x 7.5-9.05 (between the inductor and
    the output caps) and x 11.35-12.7 (against the cell boundary), which carry
    the rotated refs that do not fit in a lane.

    Bottom half (yt+CB ..), the v1 switch, unchanged in its internal geometry:
    gate network, switch, fuse, bulk decoupling, output header. The 5V
    indicator D_n2/R_n5 goes in the strip right of the radial can, with its
    refs down in the horizontal lane above the header, alongside J_n's.

    As in v1 the cell comes from one function, so all five are identical by
    construction and there is no per-channel coordinate to get wrong.
    """
    # --- top half: this port's buck ---------------------------------------
    put("C%d5" % n, x0 + 1.8, yt + 2.0, ref_at=(0, 2.4))
    put("U%d" % n, x0 + 6.4, yt + 2.0, ref_at=(0, 2.4))
    put("C%d6" % n, x0 + 10.9, yt + 2.0, ref_at=(0, 2.4))
    put("C%d4" % n, x0 + 2.6, yt + 6.3, ref_at=(0, 2.2))
    put("R%d4" % n, x0 + 6.3, yt + 6.3, 90, ref_at=(0, 2.2))
    put("R%d2" % n, x0 + 8.6, yt + 6.3, 90, ref_at=(1.0, 2.2))
    put("R%d3" % n, x0 + 10.9, yt + 6.3, 90, ref_at=(1.1, 4.7), ref_rot=90)
    put("L%d" % n, x0 + 4.0, yt + 12.9, ref_at=(0, 0))
    put("C%d7" % n, x0 + 10.2, yt + 11.5, 90, ref_at=(-1.9, 0), ref_rot=90)
    put("C%d8" % n, x0 + 10.2, yt + 16.4, 90, ref_at=(-1.9, 0), ref_rot=90)

    # --- bottom half: the v1 staggered switch ------------------------------
    put("C%d1" % n, x0 + 3.2, yt + CB + 1.4, ref_at=(-2.7, 0), ref_rot=90)
    put("D%d1" % n, x0 + 9.3, yt + CB + 1.4, ref_at=(2.9, 0), ref_rot=90)
    put("R%d1" % n, x0 + 3.2, yt + CB + 4.6, ref_at=(2.65, 0), ref_rot=90)
    put("Q%d" % n, x0 + 9.0, yt + CB + 4.6, ref_at=(2.8, 0), ref_rot=90)
    put("F%d" % n, x0 + 6.35, yt + CB + 9.0, ref_at=(-4.5, 0))
    put("C%d3" % n, x0 + 11.4, yt + CB + 9.0, 90, ref_at=(-1.5, 0), ref_rot=90)
    put("C%d2" % n, x0 + 4.6, yt + CB + 15.5, ref_at=(0.4, -2.6))
    put("D%d2" % n, x0 + 11.6, yt + CB + 13.6, 90, ref_at=(-9.6, 6.9))
    put("R%d5" % n, x0 + 11.6, yt + CB + 17.2, 90, ref_at=(-7.1, 3.3))
    put("J%d" % n, x0 + 2.54, yt + CB + 23.0, 90, ref_at=(5.0, -2.5))


for n in range(1, 6):
    channel(n, CH_X0 + (n - 1) * CW, CH_Y)

for i in range(1, 5):
    put("R6%d" % i, CH_X0 + i * CW, LINK_Y, ref_at=(0, -2.0))


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
