# 5-Bay SATA Drive Power Supply

A 5-channel 12V/5V power board for a SATA port-multiplier drive cage, with
**passive analog staggered spin-up** so five drives never draw their inrush at
the same moment.

**Two 12V DC bricks in** (one barrel jack for bays 1–3, one for bays 4–5), five
12V+5V outputs out. No MCU, no hot-swap: each half powers up and down as a unit.

| | |
|---|---|
| Status | Schematic complete and verified · PCB routed, JLCPCB 2-layer rules |
| Board | 64.9 × 78.8 mm, single-sided placement, 118 parts |
| ERC / DRC | 0 errors, 0 unconnected, 0 schematic-parity issues (93 `connection_width` warnings, 86 of them inherited from v3) |
| BOM | `kicad/digikey_bom.csv`, fully sourced |
| Tool | KiCad 9 — open `kicad/sata_psu.kicad_pro` |

Tag [`v1.0`](../../releases/tag/v1.0) is the earlier single-buck board: 56 parts,
64.2 × 53.3 mm, same switch topology.

## What it does

- **Input, ×2:** barrel jack → 8A cartridge fuse → PMOS reverse-polarity guard →
  1000µF bulk, with a 12V indicator LED tapped *after* the guard so it also
  proves the guard is conducting. `J8` feeds `12V_A` (bays 1–3), `J9` feeds
  `12V_B` (bays 4–5). See "Two inputs" below.
- **Per channel (×5):** high-side P-channel MOSFET on the 12V feed, gate driven
  by an RC network so each channel turns on ~1.5–2s after the previous one and
  ramps softly instead of slamming in; 8.2V zener gate clamp; PPTC polyfuse;
  local bulk + HF decoupling; 4-pin header (12V / GND / GND / 5V) out to a SATA
  pigtail; a 5V indicator LED at the connector.
- **No 3.3V pin anywhere**, by construction — this sidesteps the SATA PWDIS
  failure mode entirely.

## Two inputs, two separate 12V rails

A fully populated cage pulls more than one PJ-063AH should carry — the jack is
an 8A contact and the single-input board fused it at 10A. So the load is
**split**, not paralleled:

```
J8 -> F8 -> Q8 -> 12V_A -> bays 1, 2, 3     worst case ~4.4A
J9 -> F9 -> Q9 -> 12V_B -> bays 4, 5        worst case ~3.4A
```

- The two rails are **never joined**; only ground is common. Two bricks in
  parallel do not share current, and an unplugged one would be back-fed.
- A 5–6A brick per jack is enough. Each half runs on its own: with only `J8`
  plugged, bays 1–3 work and 4–5 are simply off.
- With one to three drives, use bays 1–3 and a single brick on `J8`.
- The split follows the default 5V grouping (U2 → 1–3, U4 → 4–5). A 5V group
  that straddled the two inputs would feed 5V to a drive whose 12V is
  unplugged, so `verify.py` check 5 now refuses it (`DOMAINS` in `gen_sch.py`).

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
the `.kicad_sch` sheets under `kicad/` — they are overwritten.

```bash
py sata_psu.py     # independent SKiDL reference netlist
py gen_sch.py      # build symbols + draw all 7 sheets
py verify.py       # the five checks below
```

**Do not run `gen_pcb.py` any more.** It produces an *unrouted* placement and
predates the routed board; `kicad/sata_psu.kicad_pcb` is now edited in KiCad
(or with pcbnew scripts) and is the source of truth for the layout.

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

1. Ceramic DC-bias derating will shorten the stagger versus the design table —
   the timing caps want bench tuning, or C0G/film for repeatability.
2. Linear-region SOA during the RC ramp is unverified against the real inrush.
3. The two inputs are staggered independently: bay 1 (domain A) and bay 4
   (domain B) each start their own RC ramp when their own brick is plugged in.
4. The 8A fuse cartridge's DigiKey number (`F2396-ND`) came from a web search
   of the listing, not from the cart — confirm it when ordering.

## Note on `libs/digikey/`

The vendored DigiKey KiCad library is not tracked here (12 MB, and unused — the
regulators moved to KiCad's own `Package_TO_SOT_SMD:SOT-23-6`).
`kicad/fp-lib-table` still carries the entry, so KiCad may warn about a missing
library on first open; either ignore it, drop the row, or restore the clone:

```bash
git clone --depth 1 https://github.com/Digi-Key/digikey-kicad-library libs/digikey
```
