# 5-Bay SATA Drive Power Supply

A 5-channel 12V/5V power board for a SATA port-multiplier drive cage, with
**passive analog staggered spin-up** so five drives never draw their inrush at
the same moment.

Single 12V DC brick in, five 12V+5V outputs out. No MCU, no hot-swap: the board
powers up and down as a unit.

| | |
|---|---|
| Status | Schematic complete and verified · PCB placed · **not routed** |
| Board | 64.9 × 76.0 mm, single-sided placement, 112 parts |
| ERC / DRC | 0 error-severity violations (213 unconnected pads = the unrouted nets) |
| BOM | 36 lines; 3 still need a DigiKey number |
| Tool | KiCad 9 — open `kicad/sata_psu.kicad_pro` |

Tag [`v1.0`](../../releases/tag/v1.0) is the earlier single-buck board: 56 parts,
64.2 × 53.3 mm, same switch topology.

## What it does

- **Input:** barrel jack → 10A cartridge fuse → PMOS reverse-polarity guard →
  2 × 1000µF bulk, sized for an 8–10A brick, with a 12V indicator LED tapped
  *after* the guard so it also proves the guard is conducting.
- **Per channel (×5):** high-side P-channel MOSFET on the 12V feed, gate driven
  by an RC network so each channel turns on ~1.5–2s after the previous one and
  ramps softly instead of slamming in; 8.2V zener gate clamp; PPTC polyfuse;
  local bulk + HF decoupling; 4-pin header (12V / GND / GND / 5V) out to a SATA
  pigtail; a 5V indicator LED at the connector.
- **No 3.3V pin anywhere**, by construction — this sidesteps the SATA PWDIS
  failure mode entirely.

## The 5V rail is configurable, not fixed

Every port has its own local 5V node and its own buck footprint. Adjacent nodes
are joined by 0Ω links. **How a port gets its 5V is a populate choice, not a
layout one** — there is no board variant either way:

```
        U1        U2        U3        U4        U5      <- buck sites
       5V_1 -R61- 5V_2 -R62- 5V_3 -R63- 5V_4 -R64- 5V_5
```

Two tuples at the top of `gen_sch.py` are the whole configuration:

```python
# port:    1      2      3      4      5
BUCKS = (False, True,  False, True,  False)
LINKS = (True,  True,  False, True)        # R61..R64, between port n and n+1
```

The default is the economy build — U2 feeds ports 1–3, U4 feeds 4–5. All-True
`BUCKS` with all-False `LINKS` gives one independent buck per port.

**`R63` open is not decoration.** Fitting it with both U2 and U4 populated
parallels two regulators, and two bucks with slightly different setpoints do not
share load — the higher one takes everything and goes into current limit. That
build draws fine, exports a valid netlist and passes ERC, so `verify.py` check 5
is the only thing that catches it.

This is also what fixed v1's largest problem: one 3A TPS563200 was under-rated
against a five-bay 5V rail. Capping a buck at three ports makes its worst case
2.1A, and the same part is correctly sized.

## The schematic is generated, not drawn

Every coordinate, value and part number lives in Python. Do not hand-edit
anything under `kicad/` — it is overwritten.

```bash
py sata_psu.py     # independent SKiDL reference netlist
py gen_sch.py      # build symbols + draw all 7 sheets
py verify.py       # the five checks below
py gen_pcb.py      # place all 112 parts
py check_pcb.py    # courtyard / pad / net / containment checks
```

`verify.py` cross-checks the drawn schematic against a *separately written*
SKiDL description of the same circuit, so a wire that only looks like it lands
on a pin gets caught. It runs five checks — ERC, symbol overlap, netlist
equivalence, symbol-pin-vs-pad, and the rail populate rules — each of which
exists because it catches something the others cannot see.

Details, and a list of KiCad file-format gotchas that cost real debugging time,
are in [HANDOFF.md](HANDOFF.md).

## Documents

- [`5bay_sata_psu_project.md`](5bay_sata_psu_project.md) — design intent: why
  staggered sequencing, power budget, block diagram, test plan.
- [`HANDOFF.md`](HANDOFF.md) — implementation: build pipeline, design decisions,
  placement rationale, BOM, and what changed in v2.

## Known open issues

1. **Three part types have no DigiKey number yet** — the green LED, the 1.5k and
   4.7k resistors, and the 0Ω link. Every other number here was copied from a
   real listing rather than extrapolated from a part-number pattern, so these
   are blank rather than guessed.
2. Ceramic DC-bias derating will shorten the stagger versus the design table —
   the timing caps want bench tuning, or C0G/film for repeatability.
3. Linear-region SOA during the RC ramp is unverified against the real inrush.
4. **Routing, copper pours and the single-point star ground are not done**, and
   v2 makes this harder than v1: five switching regulators, each with its own
   input loop, next to five drive connectors.

## Note on `libs/digikey/`

The vendored DigiKey KiCad library is not tracked here (12 MB, and unused — the
regulators moved to KiCad's own `Package_TO_SOT_SMD:SOT-23-6`).
`kicad/fp-lib-table` still carries the entry, so KiCad may warn about a missing
library on first open; either ignore it, drop the row, or restore the clone:

```bash
git clone --depth 1 https://github.com/Digi-Key/digikey-kicad-library libs/digikey
```
