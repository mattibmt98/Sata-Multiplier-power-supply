# 5-Bay SATA PSU — Project Handoff

Everything a fresh session needs to pick this up. The **design intent** lives in
[`5bay_sata_psu_project.md`](5bay_sata_psu_project.md); this file covers the
**implementation**: how the KiCad project is produced, why it is produced that
way, and what is still open.

---

## 1. Status

The schematic is complete, verified, and fully sourced. The PCB is **placed but
not routed**.

This is **v2**: every port has its own 5V buck, and a port may instead take 5V
from a neighbour across a 0R link. See section 11 for what changed and why.

| | |
|---|---|
| Schematic | Root + 7 hierarchical sheets (input, rails, 5 channels), KiCad 9 format |
| ERC | 0 error-severity violations |
| BOM | 36 lines; 3 of them have no DigiKey number yet (Open Issues #1) |
| Footprints | All assigned and validated against symbol pins |
| PCB placement | All 112 parts placed, front side only, 64.9 x 76.0 mm |
| PCB DRC | 0 violations (213 unconnected pads = the unrouted nets) |
| PCB routing | Not started |

Open in **`kicad/sata_psu.kicad_pro`** (KiCad 9).

---

## 2. Commands

```bash
py sata_psu.py     # reference netlist -> kicad/reference.net   (run first)
py gen_sch.py      # build symbols + draw all sheets -> kicad/
py verify.py       # the five schematic checks below; exit 0 = all pass
py gen_pcb.py      # place all 112 parts -> kicad/sata_psu.kicad_pcb
py check_pcb.py    # placement + net checks; exit 0 = all pass
```

`gen_pcb.py` reads `kicad/from_geometry.net`, which `verify.py` writes, so the
order is: `gen_sch.py` -> `verify.py` -> `gen_pcb.py` -> `check_pcb.py`.

DRC (expect 0 violations and 111 unconnected pads until routing starts):

```bash
D:/Kicad/bin/kicad-cli.exe pcb drc --format report -o kicad/drc.rpt     kicad/sata_psu.kicad_pcb
```

Exports (optional):

```bash
D:/Kicad/bin/kicad-cli.exe sch export pdf     --output kicad/sata_psu.pdf kicad/sata_psu.kicad_sch
D:/Kicad/bin/kicad-cli.exe sch export bom     --fields "Reference,Value,Footprint,MPN,DigiKey" \
    --group-by "Value,Footprint,MPN" --output kicad/bom.csv kicad/sata_psu.kicad_sch
```

**`verify.py` runs five checks. All five exist because ERC alone is not enough:**

1. **ERC** via `kicad-cli` — KiCad's own rules.
2. **Symbol overlap** — geometry. ERC passes happily on a schematic whose symbols
   are stacked on top of each other, which is exactly what the first attempt produced.
3. **Netlist equivalence** — compares the connectivity KiCad reads back off the
   drawing against the *independent* SKiDL description in `sata_psu.py`. This is
   the real proof that wires land on the pins they look like they land on.
4. **Symbol pin vs pad** — every symbol pin number must exist as a pad in its
   footprint. This caught a bug where all six MOSFETs would have imported to the
   PCB with **every pad unconnected**, invisible to ERC.
5. **Rail populate rules** — the `BUCKS`/`LINKS` combination in `gen_sch.py` is
   legal. A DNP part is still a wire in the netlist, so a build that fits `R63`
   with both `U2` and `U4` populated passes checks 1 and 3 happily and puts two
   regulators in parallel on the bench. Nothing but this check can catch it.

---

## 3. Environment

| | |
|---|---|
| KiCad | **9.0.3, installed at `D:\Kicad`** — *not* `C:\Program Files`. CLI: `D:\Kicad\bin\kicad-cli.exe` |
| Python | 3.13 via the `py` launcher |
| Packages | `skidl` 2.3.0 (reference netlist), `pymupdf` (rasterising the PDF to look at it) |
| Symbol libs | `D:/Kicad/share/kicad/symbols` — hardcoded as `sch_lib.LIBDIR` |
| Footprint libs | `D:/Kicad/share/kicad/footprints` — `sch_lib.FOOTPRINT_DIR` |

Probing `C:\Program Files\KiCad` reports KiCad as missing. Registry key
`HKLM\...\Uninstall\KiCad 9.0` → `InstallLocation` is the reliable lookup.

---

## 4. How the project is built

The schematic is **generated, not hand-drawn**. Do not hand-edit files in
`kicad/` — they are overwritten by `gen_sch.py`.

| File | Role |
|---|---|
| `gen_sch.py` | **The design.** Every coordinate, value, footprint and part number, plus `BUCKS`/`LINKS`. Start here. |
| `sch_lib.py` | Emitter. Resolves real pin geometry from the KiCad libraries and writes KiCad 9 s-expressions. Refuses off-grid placement, diagonal wires, and non-existent footprints. |
| `make_symbols.py` | Builds `libs/sata_psu.kicad_sym` (currently just AOD4185). |
| `sata_psu.py` | **Independent** SKiDL description of the same circuit. Netlist only — it does *not* draw. Exists so `verify.py` can diff two independent descriptions. |
| `verify.py` | The five checks. |
| `check_layout.py` | Overlap detection (used by `verify.py` check 2). |
| `gen_pcb.py` | **The placement.** Every board coordinate and every silkscreen reference position. Start here for the PCB. |
| `pcb_lib.py` | Board emitter. Reads real `.kicad_mod` courtyards and pad geometry, writes a KiCad 9 `.kicad_pcb` with the netlist's nets already on the pads. |
| `check_pcb.py` | Courtyard overlap, pad existence, pad-net equivalence, outline containment. |
| `libs/digikey/` | Vendored DigiKey KiCad library (git clone). **No longer used** -- see gotcha 9. |
| `libs/sata_psu.kicad_sym` | Generated project symbols. |
| `kicad/fp-lib-table`, `kicad/sym-lib-table` | Point KiCad at `libs/`. Hand-written, not generated. |

**Why not SKiDL's own schematic output?** It was tried first. Its force-directed
placer stacked symbols at identical coordinates (`R_EN` and `C_BUCK_IN` on the
exact same point), and it wrote KiCad 7 format with a project name that did not
match the `.kicad_pro`, which left every symbol's instance data unresolvable —
symbols could not even be moved in the editor. SKiDL is kept only as the
independent reference netlist.

### Layout conventions in `gen_sch.py`

* Supply rail horizontal across the top; ground symbols point down.
* Power flows left→right, top→bottom.
* Shunt parts (decoupling, dividers) hang below their rail.
* Inter-sheet nets are global labels: `12V_MAIN` board-wide, and one
  `5V_n` per port (there is no `5V_MAIN` in v2).
* All placement on the **1.27mm grid** (`sch_lib` raises if not).

---

## 5. KiCad file-format gotchas (hard-won — do not rediscover these)

These each cost real debugging time.

1. **Junctions do not bind a wire that ends mid-span of another wire.**
   KiCad stores wires **pre-split** at junction points. Emitting a long rail plus
   a junction dot produced 47 phantom "pin not connected" errors.
   `sch_lib._split_at_junctions()` handles this.

2. **References must end in digits.** KiCad parses a reference as *prefix +
   number*, so `R_EN`, `C_BST`, `C_LOC1_HF` are treated as **unannotated** and
   `kicad-cli` warns on every netlist export. Hence the current scheme, which
   keeps the channel readable in the ref: `Q3 / R3 / C31 / D3 / F3 / J3` are all
   channel 3. Blocks: 1–5 = channels, 8 = input, 9 = buck.

3. **Field angle: KiCad composes the symbol rotation for 90/270 but treats 180 as
   a mirror.** So a field angle of 180 renders upside down, while 90/270 need
   counter-rotation. Rule in `sch_lib.render()`: `fang = 90 if rot in (90,270) else 0`.
   Established by building a throwaway test sheet with a resistor at all four
   rotations and looking at the render — not by reasoning.

4. **Field text is centred**, so a long value pushes into the *neighbouring* part.
   Parts carrying long values need ~20mm of clearance, or an explicit
   `fields="left"` / `fields="above"` override.

5. **Generic symbols have named pins, real footprints have numbered pads.**
   `Device:Q_PMOS` has pins G/D/S; any real MOSFET footprint has pads 1..n. This
   mismatch is completely invisible to ERC and produces a board with unconnected
   pads. Check 4 in `verify.py` exists solely for this.

6. **Symbol instance data is keyed by project name.** `(project "...")` inside
   each symbol's `(instances ...)` must match the `.kicad_pro` filename stem, or
   KiCad cannot resolve placements.

7. Sub-sheet files carry **no** `sheet_instances`; only the root does.
   Instance paths are `/<root_uuid>/<sheet_object_uuid>`.

8. Current KiCad 9 schematic format version is **`20250114`**; the board format
   version is **`20241229`**. KiCad 9 also renumbered copper layers -- `B.Cu` is
   layer **2**, not 31. Both were taken from `D:/Kicad/share/kicad/demos`, which
   ships files in the current format, rather than guessed.

9. **A KiCad 5 `(module ...)` footprint cannot be written into a KiCad 9 board.**
   The vendored `digikey-footprints:SOT-23-6` is still in that format (no uuids,
   `fp_text reference` instead of a `property`, `(width ...)` instead of
   `(stroke ...)`). The TPS563200s use KiCad's own `Package_TO_SOT_SMD:SOT-23-6` --
   same pin numbering (1-3 one side, 4-6 the other), proper IPC land pattern,
   and no vendored library needed.

10. **In a footprint, position is footprint-local but text angle is absolute.**
    A footprint rotated 90 deg keeps its library text *offsets* unchanged and
    stores the text *angle* as 90. Pad positions likewise stay in the unrotated
    frame while pad angles get the rotation added. Established by reading a
    KiCad-written board (`demos/pic_programmer`), not by reasoning.

11. **A circle is stored as centre + a point on the rim.** Reading those two as
    plain points puts a radial capacitor's courtyard half a diameter off, which
    silently passes an overlap check that uses the same wrong box. Fixed in
    `pcb_lib._seg_pts`.

12. **The minus half of a KiCad radial-cap silkscreen is solid hatching.** There
    is no room for a reference designator there; it has to go in the plus half.

13. KiCad's default minimum silk text height is **0.8 mm** -- anything smaller
    is a DRC violation, so that is the floor when hunting for silk space.

14. **A DNP part is still a wire.** `(dnp yes)` changes the BOM and the plot; it
    does not remove the part from the netlist, so ERC and netlist equivalence
    are both blind to an illegal populate option. Every buck and every rail link
    is instantiated in `sata_psu.py` regardless of its flag, for exactly this
    reason -- the two netlists must match whatever is fitted. Which combinations
    are *allowed* is a separate question and `check_rails()` is the only thing
    that answers it.

15. **Opening the project in KiCad rewrites the generated sheets.** Eeschema
    saves them back tab-indented with `(generator "eeschema")`, which is fine
    for KiCad and fatal for any regex that expects `gen_sch.py`'s output. This
    silently broke `check_layout.py`, and the way it broke is worth keeping:
    `text[text.find(marker):]` returns the LAST CHARACTER when `find` returns
    -1, not an empty string, so the `or text` fallback never fired and the check
    reported *"0 symbols checked, 0 overlapping pairs"* and **passed**. It now
    fails loudly when it parses nothing. After opening the project in KiCad,
    re-run `gen_sch.py` before trusting check 2.

---

## 6. Design decisions worth knowing

**Two different MOSFETs, deliberately.** Q8 (reverse-polarity guard) carries the
whole board — the drives *plus* the buck's input current, ≈5.1A steady — not the
≈2A a single channel sees. In SOT-23 that is 1.6W, which is impossible; in TO-252
it is 0.39W. Per-channel switches are SOT-23 (0.24W at spin-up). This swap cut
total MOSFET courtyard area 40% (244 → 147 mm²) versus the SO-8 part used earlier.

**Zener is 8.2V, not 10V.** AO3401A is rated Vgs ±12V (the SO-8 part it replaced
was ±25V). A 10V zener at +5% is 10.5V — only 1.5V of margin against absolute
max. 8.2V gives 3.4V. It costs nothing: turn-on happens when the gate crosses
Vth (~−1.4V) early in the RC ramp, so the clamp level does not move the stagger
timing, and R_DS(on) at −8.2V is barely above the −10V figure.

**0603 imperial for passives, with two exceptions.** 10µF and 22µF ceramics are
1206 — not merely to fit the charge, but because DC-bias derating in a small case
discards most of the capacitance, and on the timing caps that directly shortens
the stagger. 1206 also had in-stock parts at 25V/50V rather than a marginal 6.3V.
Electrolytics (1000µF, 220µF) are radial THT; no chip form exists.

**Header pinout sidesteps PWDIS by construction.** J1–J5 are 4×1 2.54mm
(12V / GND / GND / 5V) wired out to SATA pigtails. There is deliberately no 3.3V
pin, so §6 of the design doc cannot bite regardless of drive model.

**Buck feedback:** Vout = 0.768 × (1 + Rn2/Rn3) = 0.768 × (1 + 56k/10k) = 5.07V.
Inductor: L = (12−5)×5 / (12 × 580kHz × 0.9A) = 5.6µH → 4.7µH standard.

**One buck per port, sized for three ports.** v1 ran a single 3A TPS563200
against doc §2's 5A target, which was the project's largest open issue. Capping
a buck at a three-port group (`MAX_GROUP`) makes its worst case 3 × ~0.7A =
2.1A, so the *same part* is now correctly sized rather than under-rated. This
is the main reason the v2 topology is worth its extra area.

**The rail links are 1206, not 0603.** A 0603 jumper is typically rated 1A. With
the buck in the middle of a three-port group each link carries one port's ~0.7A,
which leaves no margin on a part whose whole job is to be invisible. 1206 0R is
2A and costs the same. `MAX_LINK_PORTS = 1` is what forces the buck to sit in
the *middle* of its group rather than at the edge, where a link would carry two
ports' current instead of one.

**Indicator placement is diagnostic, not decorative.** The 12V LED (D81) taps
`12V_MAIN` *after* Q8, so it also proves the reverse-polarity guard is
conducting -- "jack lit but nothing works" is a different fault from "nothing
lit at all". Each 5V LED (Dn2) sits on its port's local node at the *header*
end, past the link, so it lights whether that port's 5V came from its own buck
or across a link: a dead regulator or a missing 0R reads as one dark port.
Both LEDs run ~2mA, ~12mA total, which is nothing against an 8-10A brick.

---

## 7. PCB placement

`gen_pcb.py` owns every board coordinate the way `gen_sch.py` owns every
schematic coordinate. Board-local coordinates: **(0, 0) is the top-left corner
of the outline**, and `ORIGIN` is added only on emit. No dimension was fixed in
advance -- the outline is fitted to the placement afterwards, which is what
makes the area the output rather than an input.

**Result: 64.88 x 75.97 mm = 4929 mm2**, front side only, 44% courtyard fill
(2177 mm2 of courtyard), 112 parts. 0 DRC violations.

Against v1's 3418 mm2 that is **+44%**, all of it vertical -- the width is still
pinned by the five header pitches and did not move. The sketch that preceded
this work estimated +30%; the extra came from the silk lanes (below), which were
not in that estimate and are not optional.

Bands, top to bottom, following the power:

| Band | Contents | Why |
|---|---|---|
| 1 (y 0-14) | J8 -> F8 -> Q8 -> C83, then D81/R81 | The 5.1 A input path along the top edge; the 12V LED taps the rail past Q8 |
| 2 (y 15-26) | C81, C82 bulk | The board-wide buck used to share this band; it moved into the cells, so the space to the right is now free |
| 2b (y 28.5) | R61-R64 | Each link sits **on the boundary between the two cells it joins**, so the sharing is visible on the board |
| 3 (y 31-76) | Five identical channel cells, 12.7 mm each | Header pitch sets the cell width, so board width is 5 x 12.7 plus margin |

### The channel cell

Still generated by one function, so all five are **identical by construction**.
It is now two halves, `CB` = 19.2 mm apart:

*Top half -- this port's buck.* Three rows with two horizontal **silk lanes**
between them:

| | y (cell-local) | contents |
|---|---|---|
| row A | 0.3-3.7 | C_n5, U_n, C_n6 -- input HF, regulator, bootstrap |
| lane 1 | 3.7-5.1 | references for row A |
| row B | 4.8-7.8 | C_n4, R_n4, R_n2, R_n3 -- input bulk, EN, feedback |
| lane 2 | 7.8-9.2 | references for row B |
| row C | 9.2-18.7 | L_n, with C_n7/C_n8 stacked to its right |

plus two vertical slivers in row C -- x 7.5-9.05 (between the inductor and the
output caps) and x 11.35-12.7 (against the cell boundary) -- carrying the
rotated references that do not fit in a lane.

**The lanes are why the board is 76 mm and not 74 mm.** The first attempt packed
the three rows tight, passed the courtyard check, and returned **17 silkscreen
DRC violations**: `U1`-`U5`'s references landed on their own pads, and the three
feedback resistors' references landed on each other. Courtyard clearance and
silkscreen space are different constraints, and only the second one is
discovered by DRC. Every row spacing here was set from the real courtyard boxes
(`pcb_lib.courtyard_box`), not estimated.

*Bottom half -- the v1 switch*, geometry unchanged: gate network, switch, fuse,
bulk decoupling, output header. The 5V indicator `Dn2`/`Rn5` goes in the strip
right of the radial can -- the only column-width space left -- with its
references down in the horizontal lane above the header, beside `Jn`'s.

**What sets each dimension.** Width is the five header pitches (63.5 mm) plus
margin; nothing else is close. Height is now J8's 14 mm body, the 10.5 mm radial
bulk cans, the link row, and a 43.7 mm channel cell of which 18.7 mm is the new
buck half. Shrinking the board means attacking one of those, not the small parts.

**The barrel jack overhangs the top edge on purpose.** Its pad 1 is only 1 mm
behind the body front, so a board edge flush with the front face would cut the
pad. J8 is placed so its *courtyard* meets the outline: pad 1 keeps the full
0.5 mm edge clearance, and the 0.5 mm of board left in front of the jack face is
far below the plug's barrel axis. `check_pcb.py` exempts J8 from the containment
check for this reason, and only J8.

**Not done:** routing, copper pours, and the single-point star ground of design
doc section 7. Note that v2 makes the grounding harder, not easier: there are
now five switching regulators, each with its own input loop, sitting next to
five drive connectors. Each `Cn4` must sit hard against its own `Un` VIN/GND.

## 8. BOM

36 grouped lines; regenerate with the `sch export bom` command in section 2,
which now carries a **DNP** column. In the default `BUCKS`/`LINKS` build the
DNP rows are `U1/U3/U5`, their passives, and `R63`.

Unchanged from v1: the switch half (Q, R_n1, C_n1, D_n1, F, C_n2, C_n3, J), the
input stage (J8, F8, Q8, C81-C83), and the buck's own values -- v2 instantiates
the same buck five times rather than changing it. See `kicad/bom.csv` for the
generated article; the three lines below are the only ones without sourcing.

| Ref | Value | Footprint | Status |
|---|---|---|---|
| D11-D51, D81 | GRN LED | LED_SMD:LED_0603_1608Metric | **no MPN/DigiKey yet** |
| R15-R55 (1.5k), R81 (4.7k) | 0603 | Resistor_SMD:R_0603_1608Metric | **no MPN/DigiKey yet** |
| R61-R64 | 0R, >=2A | Resistor_SMD:R_1206_3216Metric | **no MPN/DigiKey yet** |

Every DigiKey number in this project was copied from a real DigiKey product
listing -- **none were extrapolated from a part-number pattern**, even where the
pattern looked obvious. The three v2 part types above have not been looked up,
so their fields are deliberately blank rather than guessed. The 1.5k and 4.7k
would follow the `RC0603FR-07...` series already used here, and that is exactly
the extrapolation this project does not make. See Open Issues #1.

Two v1 caveats still worth re-checking at order time:

* `296-43663-1-ND` (the TPS563200) came from the DigiKey **India** listing; the
  US site showed the part backordered. v2 needs **two** of them for the default
  build and **five** if every port gets its own.
* `1276-2876-1-ND` (10uF 1206) has shown as backordered on at least one listing.
  The 22uF `1276-3047-1-ND` had ~426k in stock.

**F8 is the two fuse clips** (qty 2); the 5x20mm 10A cartridge itself is not a
PCB part and is not in the BOM.

## 9. Open issues

**1. Three v2 part types have no DigiKey number.** The green 0603 LED, the 1.5k
and 4.7k 0603 resistors, and the 1206 0R link. Blank rather than guessed, per
the sourcing rule in section 8. This is the only thing standing between the
current BOM and an order.

**2. Ceramic DC-bias derating will shift the stagger timing.**
X5R/X7R lose 50-80% of capacitance at rated DC bias, so C41/C51 will behave
smaller than marked and the real stagger will be *shorter* than the section 4
table and vary part to part. Section 10 of the design doc already calls for
bench tuning. For repeatable timing the timing caps specifically want film or
C0G rather than X5R.

**3. Linear-region SOA during the RC ramp is unverified.**
The FET spends time in its linear region while the gate ramps; this needs
checking against the chosen part's pulsed SOA curve at the real ramp time and
the drive's actual inrush profile.

**4. The board is placed but not routed.** Next major step, and bigger than it
was in v1: five switching nodes and five inductors in narrow columns. Design doc
section 7 still applies -- single-point star ground back to the brick negative,
do not split or switch ground per channel. The 12V path J8 -> F8 -> Q8 ->
channel sources carries ~5.1A and wants wide copper, as does each channel's ~2A
spin-up path. **Consider routing v1 first** as a known-good reference; it is
tagged `v1.0`.

**5. Cosmetic ERC warning.** `lib_symbol_mismatch` on the TPS563200 symbols,
because `make_symbols`/`sch_lib` flatten its `extends`. Cleared by
*Tools -> Update Symbols from Library* in Eeschema. Harmless.

**6. Only the stagger is per-channel; the 12V LED is not.** D81 shows the common
rail, so it lights before any channel switches on and says nothing about the
sequence. Design doc section 9.1 wants the turn-on order watched on the bench,
and a second LED per channel on the *switched* 12V (drain side of Qn, past the
polyfuse) would make the stagger visible as five lights coming up in turn, and
would also show a tripped polyfuse. Two parts per channel; not built.

**CLOSED in v2 -- the buck is no longer under-rated.** v1's largest open issue
was that the 3A TPS563200 sat under doc section 2's 5A five-bay rail. With
`MAX_GROUP = 3` the worst case is 2.1A and the part is correctly sized, so the
planned `TPS563300` swap is no longer needed.

## 10. Disposable files

Regenerated on every run; safe to delete, no need to keep:

```
__pycache__/  sata_psu.log  sata_psu.erc  sata_psu_sklib.py   (SKiDL output)
kicad/fp-info-cache  kicad/sata_psu-backups  kicad/*.kicad_prl (KiCad state)
kicad/board.svg                                          (board inspection)
kicad/from_geometry.net  kicad/reference.net  kicad/erc.rpt    (verify.py output)
kicad/drc.rpt                                            (kicad-cli pcb drc)
```

Everything in `kicad/*.kicad_sch` is generated by `gen_sch.py` — edit
`gen_sch.py`, not the sheets.

---

## 11. What changed in v2

v1 was one board-wide buck feeding a shared `5V_MAIN`. v2 gives every port its
own 5V node and its own buck footprint, and joins adjacent nodes with 0R links,
so **how a port gets its 5V is a populate choice rather than a layout one**:

```
        U1        U2        U3        U4        U5      <- buck sites
       5V_1 -R61- 5V_2 -R62- 5V_3 -R63- 5V_4 -R64- 5V_5
```

The configuration is two tuples at the top of `gen_sch.py`, and it is the only
thing to edit to change a build:

```python
# port:    1      2      3      4      5
BUCKS = (False, True,  False, True,  False)
LINKS = (True,  True,  False, True)        # R61..R64, between port n and n+1
```

Default is the economy build -- U2 feeds ports 1-3, U4 feeds 4-5. Setting
`BUCKS` all-True and `LINKS` all-False gives one independent buck per port. Both
are legal; `check_rails()` enforces three rules:

1. every link-joined group has **exactly one** populated buck -- zero means dead
   ports, two or more means paralleled regulators;
2. no group exceeds `MAX_GROUP` (3) ports, or the buck is over its rating;
3. no single link carries more than `MAX_LINK_PORTS` (1) ports' current, which
   in practice forces the buck into the **middle** of its group.

**`R63` being open is not decoration.** Fitting it with both U2 and U4 populated
parallels two regulators, and two bucks with slightly different setpoints do not
share load -- the higher one takes everything and goes into current limit. That
build is electrically valid, exports a clean netlist and passes ERC. Rule 1 is
the only thing that stops it, which is why it is a verify check and not a
comment.

Reference scheme, extending v1's "block prefix + digits" (gotcha 2). Blocks 1-5
are channels, **6 is the rail links**, 8 is the input; block 9 is gone with the
board-wide buck.

| Ref | Part | v1 name |
|---|---|---|
| `Qn`, `Fn`, `Jn`, `Cn1`-`Cn3` | switch, polyfuse, header, gate/decoupling | unchanged |
| `Rn1` | 220k gate pull | was `Rn` |
| `Dn1` | 8.2V zener | was `Dn` |
| `Un`, `Ln` | TPS563200, 4.7uH | were `U9`, `L9` |
| `Cn4`-`Cn8` | buck in/HF/bootstrap/out x2 | were `C91`-`C95` |
| `Rn2`, `Rn3`, `Rn4` | 56k, 10k, 100k EN | were `R92`, `R93`, `R91` |
| `Dn2`, `Rn5` | 5V indicator + 1.5k | new |
| `R61`-`R64` | 0R rail links | new |
| `D81`, `R81` | 12V indicator + 4.7k | new |

Also new: `sch_lib.Sheet.place()` takes `dnp=`, the channel and rails sheets are
**A3** (the buck block shares the channel page), and `buck_sheet()` is gone --
it is `buck_block(sh, n, dx, dy, fitted)`, drawn into each channel sheet.

**What it cost.** 56 parts -> 112, and 3418 mm2 -> 4929 mm2 (+44%). In the
default build you *populate* about 90 of the 112, but the board carries land for
all of them either way. Five switchers also mean five EMI sources next to five
drive connectors where there was one.
