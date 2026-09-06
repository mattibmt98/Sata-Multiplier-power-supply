# 5-Channel SATA Drive Power Supply — Project Draft

Design direction locked in: **passive/analog per-channel sequencing**, **single DC brick + onboard
5V regulation**, **no hot-swap** (fixed wiring, board powers up/down as a unit).

## 1. Why staggered analog sequencing at all

Directly from the multiplier debugging: a single 3.5" HDD sagged the 12V rail from 12V to **10.5V**
during a cold/wake spin-up on a 12V/1A supply. Spin-up draws ~1.5-2A peak per drive for 1-3 seconds;
steady-state run current is much lower (~0.5-0.7A). Five drives spinning up **simultaneously** would
demand a peak the brick would need to supply all at once (~7-10A instantaneous), which is both
expensive to size for and risks the same brownout/reset loop seen with the undersized single-drive
supply. Staggering each channel's turn-on by ~1.5-2s means the brick only ever has to source one
drive's spin-up peak plus four drives' steady-state current at once — a much smaller, cheaper number
to design around.

## 2. Power budget

| Rail | Per-drive spin-up peak | Per-drive steady-state | 5-drive steady-state | Worst-case instantaneous (staggered) |
|------|------------------------|-------------------------|------------------------|----------------------------------------|
| 12V  | ~1.5-2A                | ~0.5-0.7A                | ~2.5-3.5A               | ~1 spin-up (2A) + 4 steady (2.4A) ≈ **4.5A** |
| 5V   | ~0.4-0.7A (logic, no big spin-up component) | ~0.4-0.7A | ~2-3.5A | ~3.5A (no staggering needed here) |

**Design targets** (matches community consensus for fully-populated JMB575-class 5-bay boards):
- **12V rail: size the brick for 8-10A continuous.** This isn't the steady-state draw (~3.5A) — it's
  margin for an aging/high-current drive, a second simultaneous access outside the power-on sequence,
  and headroom so the rail never gets close to the sag that caused the original failure.
- **5V rail: 5A**, generated locally from the 12V input via a buck converter (not pulled from the
  brick directly, since we're using a single 12V brick as the input source).

## 3. Block diagram

```
                 ┌──────────────────────────────────────────────────────────┐
                 │                     12V DC BRICK (8-10A)                   │
                 └───────────────┬──────────────────────────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │ Reverse-polarity PMOS +  │
                    │ input fuse (10A) +       │
                    │ bulk input caps          │
                    │ (2x1000uF + 10uF ceramic)│
                    └────────────┬────────────┘
                                 │  12V_MAIN (always on)
              ┌──────────────────┼──────────────────────────────┐
              │                  │                               │
     ┌────────▼────────┐        │                      ┌─────────▼─────────┐
     │ 12V->5V buck     │        │                      │  5x staggered      │
     │ module (5A+)     │        │                      │  high-side PMOS    │
     │ e.g. TPS563201   │        │                      │  switches, RC gate │
     │ or ready module  │        │                      │  delay (see §4)    │
     └────────┬────────┘        │                      └─────────┬─────────┘
              │ 5V_MAIN                                            │
              │ (feeds all 5 bays, not switched)          12V_CH1..12V_CH5
              │                                                    │
              └──────────────┬─────────────────────┬───────────────┘
                              │                     │
                   ┌──────────▼──────────┐   (x5 channels total)
                   │ Per-channel polyfuse │
                   │ (~2.5-3A hold)       │
                   └──────────┬──────────┘
                              │
                   ┌──────────▼──────────┐
                   │ SATA power connector │
                   │ 12V + 5V + GND only  │
                   │ (3.3V/pin3 = NC,     │
                   │  see §6 PWDIS note)  │
                   └─────────────────────┘
```

## 4. Per-channel sequencing circuit (analog, no MCU)

Each of the 5 channels gets its own **P-channel MOSFET high-side switch** on the 12V feed:

- Source → 12V_MAIN. Drain → that channel's polyfuse → SATA connector 12V pin.
- Gate held high (off) via a resistor to 12V_MAIN at power-off.
- On power-up, gate is pulled toward ground through a resistor **R_n**, with a capacitor **C_n**
  from gate to source setting the RC time constant — this does two things at once:
  1. **Staggers** when each channel crosses the MOSFET's threshold and turns on.
  2. **Softens** the turn-on edge (the FET spends a moment in its linear region acting as a current
     limiter), which blunts the di/dt spike instead of slamming full spin-up current in at once.
- A **Zener diode (~10-12V) across gate-source** clamps Vgs so it doesn't exceed the MOSFET's rated
  gate voltage when driven straight off the 12V rail.

Suggested starting values for ~1.5-2s stagger between channels (tune on the bench — exact timing
depends on the specific FET's threshold and your resistor tolerance):

| Channel | R (gate pull) | C (gate-source) | Approx. turn-on order |
|---------|----------------|-------------------|-------------------------|
| 1 | 220kΩ | 1µF | ~0.2s |
| 2 | 220kΩ | 2.2µF | ~0.5s |
| 3 | 220kΩ | 4.7µF | ~1s |
| 4 | 220kΩ | 10µF | ~2.2s |
| 5 | 220kΩ | 22µF | ~4.8s |

Total power-up sequence: ~5s from brick-on to all 5 drives spinning.

**Candidate MOSFET**: any logic/low-threshold P-channel part rated for ≥4A continuous, low RDS(on)
(<50mΩ) at the gate drive voltage you end up with after the Zener clamp — e.g. AO3401A-class parts
for lower current designs, or a beefier SO-8 PMOS (e.g. AO4407A) for more margin. Confirm SOA covers
the linear-region dissipation during the RC turn-on ramp (brief, but real — a few hundred ms at a few
watts is typically fine for these packages, but check the datasheet's pulsed SOA curve at your
resistor-set ramp time).

## 5. Per-channel protection

- **Polyfuse (PPTC), ~2.5-3A hold / ~6A trip**, in series with each channel's output after the
  switch. If one drive faults (short, dead motor drawing excess current), it trips and isolates that
  bay without collapsing the shared 12V_MAIN rail or taking down the other four drives — this
  directly targets the exact failure signature seen in this investigation (one bad drive dragging the
  whole rail into a brownout loop).
- **Local decoupling** at each SATA connector: 100-220µF electrolytic + 1µF ceramic close to the
  connector. This is decoupling, not a substitute for brick sizing — it won't bridge a multi-second
  current deficit (recall: 470µF only bridges ~0.5ms at 1A deficit), it just cleans up local
  switching noise from that channel's MOSFET edge.

## 6. Important: leave the 3.3V pin (pin 3) unconnected

Standard SATA power connectors carry 3.3V, 5V, and 12V. Many drives implement **PWDIS (Power
Disable)** on the 3.3V pin — sustained 3.3V there is a legitimate hot-swap-chassis feature that tells
the drive to power itself off. A generic pass-through of 3.3V from a cheap adapter is a documented
cause of drives that won't stay spun up. Since this board only needs 12V (spin motor) and 5V (logic),
**do not route a 3.3V rail to the SATA connectors at all** — leave that pin group unconnected. This
avoids the PWDIS failure mode entirely regardless of which drives you end up using.

## 7. Grounding

Single-point star ground back to the brick's negative terminal. All 5 channels' return paths and the
5V buck's ground tie to this common point — **do not switch or split ground per channel** (this is
why channel switching is done high-side/PMOS on the 12V feed rather than low-side on the return).
Keeps every drive at the same ground reference, which matters both for signal integrity on the SATA
data side and to avoid the kind of ground-mismatch failure mode flagged earlier when the drive and
multiplier had separate, uncoordinated power domains.

## 8. Bill of materials (starting point, not final)

| Qty | Part | Notes |
|-----|------|-------|
| 1 | 12V DC barrel-jack adapter, 8-10A | Input source |
| 1 | Panel-mount barrel jack + 10A fuse holder + 10A fast-blow fuse | Input protection |
| 1 | P-channel MOSFET (reverse-polarity protection, high-current) | Input reverse-polarity guard |
| 2 | 1000µF 25V low-ESR electrolytic | Input bulk capacitance |
| 1 | 10µF ceramic | Input HF decoupling |
| 1 | 12V→5V buck converter module, 5A+ (e.g. TPS563201-based) | 5V rail, always-on |
| 5 | P-channel MOSFET, ≥4A, low RDS(on) (e.g. AO4407A or similar) | Per-channel 12V switch |
| 5 | Zener diode ~10-12V | Gate-source clamp per channel |
| 5 | Gate resistor ~220kΩ (tune per channel) | RC delay network |
| 1 each | 1µF / 2.2µF / 4.7µF / 10µF / 22µF ceramic or tantalum | RC delay caps, one value per channel |
| 5 | PPTC resettable fuse, ~2.5-3A hold | Per-channel overcurrent protection |
| 5 | 100-220µF electrolytic + 1µF ceramic | Per-channel local decoupling |
| 5 | SATA power connector (15-pin, 3.3V pin unused) | Drive power output |

## 9. Test plan (same methodology already proven in this investigation)

1. **Bench-test each channel alone** with a resistive dummy load before connecting real drives —
   confirm turn-on order and approximate timing with a multimeter/scope.
2. **Measure 12V_MAIN sag during the full 5-channel power-up sequence** with a real load (or dummy
   loads sized to mimic spin-up current) — the number to watch for is the same one that caught the
   original fault: does it stay above ~10.8V (12V -10%) at the worst moment in the sequence?
3. **Load with actual HDDs**, one channel at a time first, then all five, replicating the exact test
   process already used: watch the rail during cold spin-up, during sustained transfer, and during an
   idle→wake cycle (the 2-minute standby / 30s wake stall behavior from the multiplier testing).
4. **Fault-injection test**: short or stall one channel's load and confirm its polyfuse trips without
   the other four channels' rail sagging.

## 10. Open decisions for next pass

- Exact MOSFET part numbers (need your on-hand parts bin / preferred distributor to finalize).
- Final R/C values — the table in §4 is a starting point; real threshold voltage and gate charge for
  the chosen FET will shift actual timing, so this needs a bench iteration.
- Enclosure/connector plan for how the 5 SATA power outputs physically reach the drive bays.
