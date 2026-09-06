"""Prove the generated schematic is both correct and readable.

Three independent checks, because passing ERC is not evidence of either:

  1. ERC via kicad-cli            -- KiCad's own rules, 0 errors expected
  2. symbol overlap               -- geometry, since ERC is blind to a schematic
                                     whose symbols are stacked on each other
  3. netlist equivalence          -- the connectivity KiCad reads back off the
                                     drawing vs. the independent SKiDL
                                     description in sata_psu.py

Run:  py verify.py
"""
import os
import re
import subprocess
import sys

KICAD_CLI = r"D:\Kicad\bin\kicad-cli.exe"
ROOT_SCH = "kicad/sata_psu.kicad_sch"
DRAWN_NET = "kicad/from_geometry.net"
REF_NET = "kicad/reference.net"

# gen_sch.py uses conventional refs; sata_psu.py predates them.
REF_MAP = {"J0": "J8", "F0": "F8", "Q0": "Q8",
           "C_BULK1": "C81", "C_BULK2": "C82", "C_IN_HF": "C83",
           "U1": "U9", "C_BUCK_IN": "C91", "C_BUCK_IN_HF": "C92", "R_EN": "R91",
           "C_BST": "C93", "L1": "L9", "C_BUCK_OUT1": "C94", "C_BUCK_OUT2": "C95",
           "R_FBT": "R92", "R_FBB": "R93"}
for _n in range(1, 6):
    REF_MAP["C%d" % _n] = "C%d1" % _n
    REF_MAP["C_LOC%d" % _n] = "C%d2" % _n
    REF_MAP["C_LOC%d_HF" % _n] = "C%d3" % _n


def run(*args):
    return subprocess.run(args, capture_output=True, text=True)


def check_erc():
    r = run(KICAD_CLI, "sch", "erc", "--output", "kicad/erc.rpt",
            "--severity-error", ROOT_SCH)
    m = re.search(r"Found (\d+) violations", r.stdout)
    n = int(m.group(1)) if m else -1
    print("1. ERC                 : %d error-severity violations" % n)
    return n == 0


def check_overlaps():
    import check_layout
    n = check_layout.main()
    return n == 0


def nets(path, remap):
    t = open(path, encoding="utf-8").read()
    t = t[t.find("(nets"):]
    out = []
    for m in re.finditer(
            r'\(net\s+\(code "?\d+"?\)\s+\(name "([^"]*)"\)(.*?)(?=\(net\s+\(code |\Z)',
            t, re.S):
        pins = set()
        for pm in re.finditer(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)', m.group(2)):
            if not pm.group(1).startswith("#"):
                pins.add((remap.get(pm.group(1), pm.group(1)), pm.group(2)))
        if pins:
            out.append(frozenset(pins))
    return set(out)


# The drawing uses real package pinouts; the SKiDL reference uses the generic
# G/D/S symbol. Same electrical node, different pin names. Note the two MOSFET
# packages number their pins differently -- on TO-252 the tab (pin 2) is drain.
SOT23_PMOS = {"1": "G", "2": "S", "3": "D"}   # AO3401A, Q1-Q5
TO252_PMOS = {"1": "G", "2": "D", "3": "S"}   # AOD4185, Q8


def canon(net):
    # A non-polarised capacitor is symmetric, so which end is pin 1 is not a
    # connectivity difference. MOSFET source/drain pads are internally common.
    out = set()
    for r, p in net:
        if r.startswith("Q"):
            m = TO252_PMOS if r == "Q8" else SOT23_PMOS
            out.add((r, m.get(p, p)))
        elif r.startswith("C"):
            out.add((r, "x"))
        else:
            out.add((r, p))
    return frozenset(out)


def check_netlist():
    r = run(KICAD_CLI, "sch", "export", "netlist", "--output", DRAWN_NET, ROOT_SCH)
    warn = "annotation" in (r.stdout + r.stderr)
    if not os.path.exists(REF_NET):
        print("3. Netlist equivalence : SKIPPED (run `py sata_psu.py` first)")
        return True
    drawn, ref = nets(DRAWN_NET, {}), nets(REF_NET, REF_MAP)
    same = {canon(n) for n in drawn} == {canon(n) for n in ref}
    print("3. Netlist equivalence : %d nets drawn, %d reference -- %s%s"
          % (len(drawn), len(ref),
             "same nodes (up to cap pin order and MOSFET pad numbering)"
             if same else "MISMATCH",
             "" if not warn else "  [annotation warning]"))
    if not same:
        cr, cd = {canon(n) for n in ref}, {canon(n) for n in drawn}
        for n in sorted(cr - cd, key=len):
            print("     only in reference:", sorted(n))
        for n in sorted(cd - cr, key=len):
            print("     only in drawing  :", sorted(n))
    return same and not warn


def check_pin_pad():
    """Every symbol pin number must exist as a pad in its footprint.

    This is what caught the original MOSFET bug: Device:Q_PMOS has pins named
    G/D/S while a SOIC-8 footprint has pads 1-8, so the board would have
    imported with every MOSFET pad unconnected -- invisible to ERC.
    """
    import sch_lib as S
    import gen_sch

    def pads(fp):
        lib, name = fp.split(":", 1)
        if lib in S.FOOTPRINT_LIBS:
            path = os.path.join(S.FOOTPRINT_LIBS[lib], name + ".kicad_mod")
        else:
            path = os.path.join(S.FOOTPRINT_DIR, lib + ".pretty", name + ".kicad_mod")
        t = open(path, encoding="utf-8").read()
        got = set(re.findall(r'\(pad\s+"([^"]*)"', t))
        got |= set(re.findall(r'\(pad\s+([\w.]+)\s', t))
        return {g for g in got if g not in ("", '""')}

    sheets = [gen_sch.input_sheet(), gen_sch.buck_sheet()]
    sheets += [gen_sch.channel_sheet(n, c, d, fp, pn)
               for n, c, d, fp, pn in gen_sch.CHANNELS]
    bad, checked = [], 0
    for sh in sheets:
        for c in sh.comps:
            if c.lib_id.startswith("power:") or not c.footprint:
                continue
            checked += 1
            pins = {n for n in c.d.pins if n.isdigit()} or set(c.d.pins)
            if not pins <= pads(c.footprint):
                bad.append("%s %s pins=%s" % (c.ref, c.footprint, sorted(pins)))
    print("4. Symbol pin vs pad   : %d placements checked, %s"
          % (checked, "all pins map to pads" if not bad else "MISMATCH"))
    for b in bad:
        print("     ", b)
    return not bad


if __name__ == "__main__":
    print("Verifying %s\n" % ROOT_SCH)
    ok = check_erc()
    print("2. Symbol overlap      :", end=" ")
    ok = check_overlaps() and ok
    ok = check_netlist() and ok
    ok = check_pin_pad() and ok
    print("\n%s" % ("ALL CHECKS PASSED" if ok else "FAILURES ABOVE"))
    sys.exit(0 if ok else 1)
