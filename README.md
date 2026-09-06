# 5-Bay SATA Drive Power Supply — v1

A 5-channel 12V/5V power board for a SATA port-multiplier drive cage, with
**passive analog staggered spin-up** so five drives never draw their inrush at
the same moment.

Single 12V DC brick in, five 12V+5V outputs out. No MCU, no hot-swap: the board
powers up and down as a unit.

| | |
|---|---|
| Status | Schematic complete and verified · PCB placed · **not routed** |
| Board | 64.2 × 53.3 mm, single-sided placement, 56 parts |
| ERC / DRC | 0 error-severity violations (111 unconnected pads = the unrouted nets) |
| BOM | 23 lines, every one with MPN + DigiKey part number |
| Tool | KiCad 9 — open `kicad/sata_psu.kicad_pro` |

## What it does

- **Input:** barrel jack → 10A cartridge fuse → PMOS reverse-polarity guard →
  2 × 1000µF bulk. Sized for an 8–10A brick.
- **5V rail:** onboard TPS563200 buck, 12V → 5.07V, always on, shared by all bays.
- **Per channel (×5):** high-side P-channel MOSFET on the 12V feed, gate driven
  by an RC network so each channel turns on ~1.5–2s after the previous one and
  ramps softly instead of slamming in; 8.2V zener gate clamp; PPTC polyfuse;
  local bulk + HF decoupling; 4-pin header (12V / GND / GND / 5V) out to a SATA
  pigtail.
- **No 3.3V pin anywhere**, by construction — this sidesteps the SATA PWDIS
  failure mode entirely.

## The schematic is generated, not drawn

Every coordinate, value and part number lives in Python. Do not hand-edit
anything under `kicad/` — it is overwritten.

```bash
py sata_psu.py     # independent SKiDL reference netlist
py gen_sch.py      # build symbols + draw all 7 sheets
py verify.py       # ERC + overlap + netlist-equivalence + pin-vs-pad checks
py gen_pcb.py      # place all 56 parts
py check_pcb.py    # courtyard / pad / net / containment checks
```

`verify.py` cross-checks the drawn schematic against a *separately written*
SKiDL description of the same circuit, so a wire that only looks like it lands
on a pin gets caught. Details, and a list of KiCad file-format gotchas that cost
real debugging time, are in [HANDOFF.md](HANDOFF.md).

## Documents

- [`5bay_sata_psu_project.md`](5bay_sata_psu_project.md) — design intent: why
  staggered sequencing, power budget, block diagram, test plan.
- [`HANDOFF.md`](HANDOFF.md) — implementation: build pipeline, design decisions,
  placement rationale, BOM, and open issues.

## Known open issues

1. **The buck is under-rated.** TPS563200 is a 3A part against a 5V rail target
   of up to ~3.5A steady. `TPS563300` (~6A) is pin-similar and the change is
   contained to `buck_sheet()` in `gen_sch.py`.
2. Ceramic DC-bias derating will shorten the stagger versus the design table —
   the timing caps want bench tuning, or C0G/film for repeatability.
3. Linear-region SOA during the RC ramp is unverified against the real inrush.
4. **Routing, copper pours and the single-point star ground are not done.**

## Note on `libs/digikey/`

The vendored DigiKey KiCad library is not tracked here (12 MB, and unused — U9
moved to KiCad's own `Package_TO_SOT_SMD:SOT-23-6`). `kicad/fp-lib-table` still
carries the entry, so KiCad may warn about a missing library on first open;
either ignore it, drop the row, or restore the clone:

```bash
git clone --depth 1 https://github.com/Digi-Key/digikey-kicad-library libs/digikey
```
