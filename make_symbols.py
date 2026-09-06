"""Build the project symbol library: libs/sata_psu.kicad_sym.

Why this exists: a generic symbol like Device:Q_PMOS has pins named G/D/S, but
every real MOSFET footprint has numbered pads. Using the generic symbol would
import to the PCB with every MOSFET pad unconnected -- and ERC cannot see it.

Q1-Q5 use Transistor_FET:AO3401A, which KiCad already ships with the correct
SOT-23 numbering (1=G 2=S 3=D). Q8 is an AOD4185 in TO-252, which KiCad does
not ship, so it is re-derived here from SUD50P04-08 -- the same TO-252
P-channel pinout (1=G 2=D 3=S, tab is drain). Both donors have pin coordinates
identical to Device:Q_PMOS, so these swaps move no wires.
"""
import os
import re
import sch_lib as S

OUT = "libs/sata_psu.kicad_sym"

HEADER = """(kicad_symbol_lib
\t(version 20241209)
\t(generator "sata_psu_gen")
\t(generator_version "9.0")
"""

# new name, source library, source symbol, value, datasheet, description
PARTS = [
    ("AOD4185", "Transistor_FET", "SUD50P04-08", "AOD4185",
     "https://aosmd.com/pdfs/datasheet/AOD4185.pdf",
     "-40A Id, -40V Vds, P-Channel MOSFET, 15mOhm Rds(on), TO-252"),
]

# What each derived symbol must look like once resolved.
EXPECTED = {"AOD4185": {"1": "G", "2": "D", "3": "S"}}


def derive(new_name, src_lib, src_sym, value, datasheet, description):
    # Use the FLATTENED block: donors often (extends ...) another symbol, and
    # that parent will not exist in the project library.
    blk = S.SymDef(src_lib, src_sym).block
    # Rename the symbol and its unit sub-symbols.
    blk = blk.replace('"%s_' % src_sym, '"%s_' % new_name)
    blk = blk.replace('(symbol "%s:%s"' % (src_lib, src_sym),
                      '(symbol "%s"' % new_name, 1)
    for prop, val in (("Value", value), ("Datasheet", datasheet),
                      ("Description", description)):
        blk = re.sub(r'\(property "%s" "[^"]*"' % prop,
                     '(property "%s" "%s"' % (prop, val), blk, count=1)
    return blk


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    body = "".join(derive(*p) for p in PARTS)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(HEADER + body + ")\n")

    # Re-read and assert the pinout came out as intended.
    S._libcache.pop("sata_psu", None)
    S._symcache.clear()
    for name, _, _, _, _, _ in PARTS:
        sd = S.symdef("sata_psu:" + name)
        got = {n: nm for nm in ("G", "D", "S")
               for n in sd.pins if n.isdigit() and sd.pins[n] == sd.pins[nm]}
        want = EXPECTED[name]
        if got != want:
            raise SystemExit("%s pinout is %s, expected %s" % (name, got, want))
        print("%s: pins %s  (verified)"
              % (name, " ".join("%s=%s" % (k, want[k]) for k in sorted(want))))


if __name__ == "__main__":
    main()
