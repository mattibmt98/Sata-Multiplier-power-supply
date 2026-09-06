# 5-Bay SATA PSU — Project Handoff

Everything a fresh session needs to pick this up. The **design intent** lives in
[`5bay_sata_psu_project.md`](5bay_sata_psu_project.md); this file covers the
**implementation**: how the KiCad project is produced, why it is produced that
way, and what is still open.

---

## 1. Status

The schematic is complete, verified, and fully sourced. The PCB is **placed but
not routed**.

| | |
|---|---|
| Schematic | Root + 7 hierarchical sheets (input, buck, 5 channels), KiCad 9 format |
| ERC | 0 error-severity violations |
| BOM | 23 lines, every one with MPN + DigiKey number |
| Footprints | All assigned and validated against symbol pins |
| PCB placement | All 56 parts placed, front side only, 64.2 x 53.3 mm |
| PCB DRC | 0 violations (111 unconnected pads = the unrouted nets) |
| PCB routing | Not started |

Open in **`kicad/sata_psu.kicad_pro`** (KiCad 9).

---

## 2. Commands

```bash
py sata_psu.py     # reference netlist -> kicad/reference.net   (run first)
py gen_sch.py      # build symbols + draw all sheets -> kicad/
py verify.py       # the four schematic checks below; exit 0 = all pass
py gen_pcb.py      # place all 56 parts -> kicad/sata_psu.kicad_pcb
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

**`verify.py` runs four checks. All four exist because ERC alone is not enough:**

1. **ERC** via `kicad-cli` — KiCad's own rules.
2. **Symbol overlap** — geometry. ERC passes happily on a schematic whose symbols
   are stacked on top of each other, which is exactly what the first attempt produced.
3. **Netlist equivalence** — compares the connectivity KiCad reads back off the
   drawing against the *independent* SKiDL description in `sata_psu.py`. This is
   the real proof that wires land on the pins they look like they land on.
4. **Symbol pin vs pad** — every symbol pin number must exist as a pad in its
   footprint. This caught a bug where all six MOSFETs would have imported to the
   PCB with **every pad unconnected**, invisible to ERC.

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
| `gen_sch.py` | **The design.** Every coordinate, value, footprint and part number. Start here. |
| `sch_lib.py` | Emitter. Resolves real pin geometry from the KiCad libraries and writes KiCad 9 s-expressions. Refuses off-grid placement, diagonal wires, and non-existent footprints. |
| `make_symbols.py` | Builds `libs/sata_psu.kicad_sym` (currently just AOD4185). |
| `sata_psu.py` | **Independent** SKiDL description of the same circuit. Netlist only — it does *not* draw. Exists so `verify.py` can diff two independent descriptions. |
| `verify.py` | The four checks. |
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
* Inter-sheet nets are global labels: `12V_MAIN`, `5V_MAIN`.
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
   `(stroke ...)`). U9 now uses KiCad's own `Package_TO_SOT_SMD:SOT-23-6` --
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

**Buck feedback:** Vout = 0.768 × (1 + R92/R93) = 0.768 × (1 + 56k/10k) = 5.07V.
Inductor: L = (12−5)×5 / (12 × 580kHz × 0.9A) = 5.6µH → 4.7µH standard.

---

## 7. PCB placement

`gen_pcb.py` owns every board coordinate the way `gen_sch.py` owns every
schematic coordinate. Board-local coordinates: **(0, 0) is the top-left corner
of the outline**, and `ORIGIN` is added only on emit. No dimension was fixed in
advance -- the outline is fitted to the placement afterwards, which is what
makes the area the output rather than an input.

**Result: 64.16 x 53.27 mm = 3418 mm2**, front side only, 48% courtyard fill
(1633 mm2 of courtyard). 0 DRC violations.

Three bands, top to bottom, following the power:

| Band | Contents | Why |
|---|---|---|
| 1 (y 0-14) | J8 -> F8 -> Q8 -> C83 | The 5.1 A input path, straight and short along the top edge |
| 2 (y 15-26) | C81, C82 bulk, then the whole buck left to right | Bulk sits next to the input; buck output lands above the channels it feeds |
| 3 (y 27-52) | Five identical channel cells, 12.7 mm each | Header pitch sets the cell width, so the board width is 5 x 12.7 plus margin |

The channel cells come from one function, so all five are **identical by
construction** -- there is no per-channel coordinate to get wrong. Within a
cell, top to bottom: gate network (C_n1, D_n), switch (R_n, Q_n), fuse (F_n,
C_n3), bulk decoupling (C_n2), output header (J_n).

**What sets each dimension.** Width is the five header pitches (63.5 mm) plus
margin; nothing else is close. Height is J8's 14 mm body, plus the 10.5 mm
radial bulk cans, plus the 24.5 mm channel cell. Shrinking the board further
means attacking one of those three, not the small parts.

**The barrel jack overhangs the top edge on purpose.** Its pad 1 is only 1 mm
behind the body front, so a board edge flush with the front face would cut the
pad. J8 is placed so its *courtyard* meets the outline: pad 1 keeps the full
0.5 mm edge clearance, and the 0.5 mm of board left in front of the jack face
is far below the plug's barrel axis. `check_pcb.py` exempts J8 from the
containment check for this reason, and only J8.

**Silkscreen.** At this density there are no horizontal lanes left inside a
channel cell, so most references are rotated 90 deg and parked in named
vertical slivers between parts (listed in `channel()`'s docstring); the
electrolytics carry theirs inside their own can, in the plus half. Every
reference position is explicit in `gen_pcb.py` -- none are left where the
footprint library put them.

**Not done:** routing, copper pours, and the single-point star ground of design
doc section 7. The placement supports it -- all five channel returns and the
buck ground sit in one band below the bulk caps -- but nothing enforces it yet.

---

## 8. BOM

| Ref | Value | Footprint | MPN | DigiKey |
|---|---|---|---|---|
| C11,C13,C23,C33,C43,C53 | 1uF | C_0603_1608Metric | CL10A105KB8NNNC | 1276-1860-1-ND |
| C12,C22,C32,C42,C52 | 220uF/25V | CP_Radial_D8.0mm_P3.50mm | UVZ1E221MPD | 493-1302-ND |
| C21 | 2.2uF | C_0603_1608Metric | CL10A225KO8NNNC | 1276-1040-1-ND |
| C31 | 4.7uF | C_0603_1608Metric | CL10A475KO8NNNC | 1276-1784-1-ND |
| C41 | 10uF | C_1206_3216Metric | CL31A106KBHNNNE | 1276-2876-1-ND |
| C51 | 22uF | C_1206_3216Metric | CL31A226KAHNNNE | 1276-3047-1-ND |
| C81,C82 | 1000uF/25V | CP_Radial_D10.0mm_P5.00mm | UVR1E102MPD | 493-1065-ND |
| C83,C91 | 10uF/50V | C_1206_3216Metric | CL31A106KBHNNNE | 1276-2876-1-ND |
| C92,C93 | 100nF | C_0603_1608Metric | CL10B104KB8NNNC | 1276-1000-1-ND |
| C94,C95 | 22uF/25V | C_1206_3216Metric | CL31A226KAHNNNE | 1276-3047-1-ND |
| D1-D5 | 8.2V | D_SOD-123 | MMSZ5237B-7-F | MMSZ5237B-FDICT-ND |
| F1-F5 | 2.6A/5.2A | Fuse_1812_4532Metric | 1812L260/16MR | F10827CT-ND |
| F8 | 10A fast-blow | Fuseholder_Clip-5x20mm_Bel_FC-203-22 | FC-203-22 | 507-1703-ND |
| J1-J5 | 12V/GND/GND/5V | PinHeader_1x04_P2.54mm_Vertical | PRPC004SAAN-RC | S1011EC-04-ND |
| J8 | 12V DC 8-10A | BarrelJack_CUI_PJ-063AH_Horizontal | PJ-063AH | CP-063AH-ND |
| L9 | 4.7uH/4.5A | L_Bourns_SRN6045TA | SRN6045TA-4R7M | SRN6045TA-4R7MTR-ND |
| Q1-Q5 | AO3401A | SOT-23 | AO3401A | 785-1001-1-ND |
| Q8 | AOD4185 | TO-252-3_TabPin2 | AOD4185 | 785-1222-2-ND |
| R1-R5 | 220k | R_0603_1608Metric | RC0603FR-07220KL | 311-220KHRCT-ND |
| R91 | 100k | R_0603_1608Metric | RC0603FR-07100KL | 311-100KHRCT-ND |
| R92 | 56k | R_0603_1608Metric | RC0603FR-0756KL | 311-56KHRCT-ND |
| R93 | 10k | R_0603_1608Metric | RC0603FR-0710KL | 311-10.0KHRCT-ND |
| U9 | TPS563200 | SOT-23-6 | TPS563200DDCR | 296-43663-1-ND |

Every DigiKey number was taken from a DigiKey product listing — none were
extrapolated from part-number patterns, even where the pattern looked obvious.
Two caveats worth re-checking at order time:

* `296-43663-1-ND` (U9) came from the DigiKey **India** listing; the US site
  shows the part backordered (see Open Issues #1).
* `1276-2876-1-ND` (10µF 1206) has shown as backordered on at least one listing.
  The 22µF `1276-3047-1-ND` had ~426k in stock.

**F8 is the two fuse clips** (qty 2); the 5×20mm 10A cartridge itself is not a
PCB part and is not in the BOM.

---

## 9. Open issues

**1. The buck regulator is under-rated — the significant one.**
TPS563200 is a **3A** part; §2 of the design doc targets a **5A** 5V rail with
2–3.5A steady-state. That is below worst-case steady state, not short on margin.
DigiKey US also shows it **backordered**. `TPS563300` (~6A) is in-library and
pin-similar. The whole regulator lives in `buck_sheet()` in `gen_sch.py`, so the
change is contained. A warning to this effect is printed on the buck sheet itself.

**2. Ceramic DC-bias derating will shift the stagger timing.**
X5R/X7R lose 50–80% of capacitance at rated DC bias, so C41/C51 will behave
smaller than marked and the real stagger will be *shorter* than the §4 table and
vary part to part. §10 already calls for bench tuning. For repeatable timing the
timing caps specifically want film or C0G rather than X5R.

**3. Linear-region SOA during the RC ramp is unverified.**
§4 flags it. The FET spends time in its linear region while the gate ramps; this
needs checking against the chosen part's pulsed SOA curve at the real ramp time
and the drive's actual inrush profile.

**4. The board is placed but not routed.** Next major step. Note design doc §7:
single-point star ground back to the brick negative; do not split or switch
ground per channel. The 12V path J8 -> F8 -> Q8 -> channel sources carries
~5.1A and wants wide copper, as does each channel's ~2A spin-up path.

**5. Cosmetic ERC warning.** `lib_symbol_mismatch` on U9, because
`make_symbols`/`sch_lib` flatten the TPS563200 `extends`. Cleared by
*Tools → Update Symbols from Library* in Eeschema. Harmless.

---

## 10. Disposable files

Regenerated on every run; safe to delete, no need to keep:

```
__pycache__/  sata_psu.log  sata_psu.erc  sata_psu_sklib.py   (SKiDL output)
kicad/fp-info-cache  kicad/sata_psu-backups  kicad/*.kicad_prl (KiCad state)
kicad/from_geometry.net  kicad/reference.net  kicad/erc.rpt    (verify.py output)
kicad/drc.rpt                                            (kicad-cli pcb drc)
```

Everything in `kicad/*.kicad_sch` is generated by `gen_sch.py` — edit
`gen_sch.py`, not the sheets.
