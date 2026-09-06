"""Lay out and emit the 5-bay SATA PSU schematic as readable KiCad 9 sheets.

Every coordinate here is deliberate and on the 1.27mm grid. Conventions used
throughout, so the sheets read the way a person would draw them:

  * supply rail runs horizontally across the top, ground symbols point down
  * power flows left to right, top to bottom
  * shunt parts (decoupling, dividers) hang below their rail
  * inter-sheet connections are global labels: 12V_MAIN, 5V_MAIN

sch_lib resolves real pin geometry from the KiCad libraries and refuses any
off-grid placement, diagonal wire, or non-existent footprint, so wires provably
land on pins and every footprint provably resolves.
"""
import os
import sch_lib as S
import make_symbols

PROJECT = "sata_psu"
OUT = "kicad"

# --------------------------------------------------------------- footprints
# Passives are 0603 imperial (1608 metric) as requested. Two exceptions:
#   10uF and 22uF ceramics -> 1206. Not only about fitting the charge: DC-bias
#     derating in a small case discards most of the capacitance, and on the
#     timing caps (C41/C51) that directly shortens the stagger. 1206 also got
#     in-stock parts with a 25V/50V rating rather than a marginal 6.3V one.
#   C81/C82 and Cn2 electrolytics -> radial THT, no chip form exists.
FP_R0603 = "Resistor_SMD:R_0603_1608Metric"
FP_C0603 = "Capacitor_SMD:C_0603_1608Metric"
FP_C1206 = "Capacitor_SMD:C_1206_3216Metric"
FP_CP_D8 = "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm"
FP_CP_D10 = "Capacitor_THT:CP_Radial_D10.0mm_P5.00mm"
FP_SOT23 = "Package_TO_SOT_SMD:SOT-23"
FP_TO252 = "Package_TO_SOT_SMD:TO-252-3_TabPin2"
FP_SOD123 = "Diode_SMD:D_SOD-123"
FP_FUSE1812 = "Fuse:Fuse_1812_4532Metric"
FP_HDR4 = "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
FP_JACK = "Connector_BarrelJack:BarrelJack_CUI_PJ-063AH_Horizontal"
FP_IND = "Inductor_SMD:L_Bourns_SRN6045TA"
FP_FUSEHOLDER = ("Fuse:Fuseholder_Clip-5x20mm_Bel_FC-203-22_Lateral_"
                 "P17.80x5.00mm_D1.17mm_Horizontal")
# KiCad's own SOT-23-6, not the DigiKey library's: that one is still in the
# KiCad 5 (module ...) format, which cannot be written into a KiCad 9 board.
# Same pin numbering (1-3 one side, 4-6 the other), proper IPC land pattern.
FP_SOT23_6 = "Package_TO_SOT_SMD:SOT-23-6"
# The 5V rail links are 1206, not 0603, on purpose. A 0603 jumper is typically
# rated 1A; a link between a buck and its neighbour carries that neighbour's
# full ~0.7A steady, which leaves no margin on a part whose whole job is to be
# invisible. 1206 0R is 2A and costs the same.
FP_R1206 = "Resistor_SMD:R_1206_3216Metric"
FP_LED0603 = "LED_SMD:LED_0603_1608Metric"

# --------------------------------------------------------------- part numbers
# Two different MOSFETs, because they carry very different currents.
#
# Q1-Q5, AO3401A: -30V, -4A, SOT-23. Each channel sees ~0.7A steady and ~2A at
#   spin-up, so ~0.24W worst case -- comfortable in SOT-23.
# Q8, AOD4185: -40V, -40A, 15mohm, TO-252. Q8 carries the WHOLE board -- the
#   drives plus the buck's input current, ~5.1A steady -- which is 1.6W in a
#   SOT-23 and only 0.39W here. That is why it is not the same part.
MPN_PMOS, DK_PMOS = "AO3401A", "785-1001-1-ND"       # SOT-23, per channel
MPN_PMOS8, DK_PMOS8 = "AOD4185", "785-1222-2-ND"     # TO-252, Q8
# MMSZ5237B-7-F: 8.2V +/-5%, 500mW, SOD-123.
#
# 8.2V rather than 10V because AO3401A is rated Vgs = +/-12V (the AO4407A this
# replaced was +/-25V). A 10V zener at +5% is 10.5V, leaving only 1.5V of margin
# against absolute max; 8.2V at +5% is 8.6V, leaving 3.4V.
#
# It costs nothing: turn-on happens when the gate crosses Vth (~-1.4V) early in
# the RC ramp, so the clamp level does not move the stagger timing at all, and
# AO3401A RDS(on) at -8.2V is barely above its -10V figure. Clamp current is
# only 12V/220k = 55uA, so a 500mW part is enormously derated either way.
MPN_ZENER, DK_ZENER = "MMSZ5237B-7-F", "MMSZ5237B-FDICT-ND"
MPN_BUCK, DK_BUCK = "TPS563200DDCR", "296-43663-1-ND"
MPN_R = {"220k": ("RC0603FR-07220KL", "311-220KHRCT-ND"),
         "100k": ("RC0603FR-07100KL", "311-100KHRCT-ND"),
         "56k":  ("RC0603FR-0756KL",  "311-56KHRCT-ND"),
         "10k":  ("RC0603FR-0710KL",  "311-10.0KHRCT-ND"),
         # Deliberately blank. Every other number in this file was copied from
         # a real DigiKey listing; none were extrapolated from a part-number
         # pattern, even where the pattern was obvious. These three are new to
         # v2 and have not been looked up yet -- see Open Issues.
         "1.5k": ("", ""),
         "4.7k": ("", "")}
MPN_R0 = ("", "")      # 0R 1206 rail link, >=2A       -- number not looked up
MPN_LED = ("", "")     # green 0603, ~2mA, Vf ~2.0V    -- number not looked up
# Ceramics: 0603 for small values, 1206 for 10uF/22uF. 1206 is not only about
# fitting the charge -- DC-bias derating in a small case throws away most of
# the capacitance, and on the timing caps that directly shifts the stagger.
C_100N = ("CL10B104KB8NNNC", "1276-1000-1-ND")
C_1U   = ("CL10A105KB8NNNC", "1276-1860-1-ND")
C_2U2  = ("CL10A225KO8NNNC", "1276-1040-1-ND")
C_4U7  = ("CL10A475KO8NNNC", "1276-1784-1-ND")
C_10U  = ("CL31A106KBHNNNE", "1276-2876-1-ND")
C_22U  = ("CL31A226KAHNNNE", "1276-3047-1-ND")
CP_220U  = ("UVZ1E221MPD", "493-1302-ND")
CP_1000U = ("UVR1E102MPD", "493-1065-ND")
MPN_L, DK_L = "SRN6045TA-4R7M", "SRN6045TA-4R7MTR-ND"
MPN_PPTC, DK_PPTC = "1812L260/16MR", "F10827CT-ND"
MPN_CLIP, DK_CLIP = "FC-203-22", "507-1703-ND"
MPN_HDR, DK_HDR = "PRPC004SAAN-RC", "S1011EC-04-ND"
MPN_JACK, DK_JACK = "PJ-063AH", "CP-063AH-ND"

# Stagger table from 5bay_sata_psu_project.md section 4: R fixed, C sets delay.
CHANNELS = [
    (1, "1uF",   "~0.2s", FP_C0603, C_1U),
    (2, "2.2uF", "~0.5s", FP_C0603, C_2U2),
    (3, "4.7uF", "~1s",   FP_C0603, C_4U7),
    (4, "10uF",  "~2.2s", FP_C1206, C_10U),
    (5, "22uF",  "~4.8s", FP_C1206, C_22U),
]

# --------------------------------------------------------- 5V rail topology
#
# Every port has its own local 5V node (5V_1..5V_5) and its own buck footprint.
# Adjacent nodes are joined by a 0R link, R61..R64. Populating a subset of the
# bucks and a subset of the links is how a build chooses between "one buck per
# port" and "one buck shared with its neighbours" -- with no layout variant,
# since the lands are always there.
#
#          U1        U2        U3        U4        U5      <- buck sites
#         5V_1 -R61- 5V_2 -R62- 5V_3 -R63- 5V_4 -R64- 5V_5
#
# The default below is the economy build: U2 feeds ports 1-3, U4 feeds 4-5.
# R63 is left OPEN, and that is not decoration -- fitting it parallels U2 and
# U4, and two bucks with slightly different setpoints do not share load, the
# higher one takes everything and hits current limit. check_rails() below is
# what stops that reaching a board, because nothing else can: a DNP part is
# still a wire to ERC and to the netlist.
#
# port:    1      2      3      4      5
BUCKS = (False, True,  False, True,  False)
LINKS = (True,  True,  False, True)        # R61..R64, between port n and n+1

MAX_GROUP = 3       # ports one buck may feed: 3 x ~0.7A = 2.1A on a 3A part
MAX_LINK_PORTS = 1  # ports one 0R link may carry: 1 x ~0.7A on a 2A jumper


def rail_groups(links=LINKS):
    """Partition the five ports into link-connected groups, left to right."""
    groups, cur = [], [1]
    for i, fitted in enumerate(links, start=1):
        if fitted:
            cur.append(i + 1)
        else:
            groups.append(cur)
            cur = [i + 1]
    groups.append(cur)
    return groups


def check_rails(bucks=BUCKS, links=LINKS):
    """Return the list of reasons this populate configuration is illegal.

    Three rules, all of which a netlist and an ERC run are blind to:
      1. every group of link-joined ports needs exactly one populated buck --
         zero means dead ports, two or more means paralleled regulators;
      2. no group may exceed MAX_GROUP ports, or the buck is over its rating;
      3. no single 0R link may carry more than MAX_LINK_PORTS ports' current,
         which in practice means the buck sits in the MIDDLE of its group,
         not at the edge.
    """
    errs = []
    for g in rail_groups(links):
        fitted = [n for n in g if bucks[n - 1]]
        if len(fitted) != 1:
            errs.append("ports %s: %d populated bucks, need exactly 1"
                        % (g, len(fitted)))
        if len(g) > MAX_GROUP:
            errs.append("ports %s: group of %d exceeds MAX_GROUP=%d"
                        % (g, len(g), MAX_GROUP))
        if len(fitted) != 1:
            continue
        src = fitted[0]
        # Each link inside the group carries every port on its far side.
        for a, b in zip(g, g[1:]):
            far = len([n for n in g if n > a]) if src <= a else len([n for n in g if n <= a])
            if far > MAX_LINK_PORTS:
                errs.append("link R6%d (ports %d-%d) carries %d ports' current, "
                            "max %d -- move the buck to the middle of %s"
                            % (a, a, b, far, MAX_LINK_PORTS, g))
    return errs


# ------------------------------------------------------------------ channel
def channel_sheet(n, c_gate, delay, c_fp, c_pn):
    """One port: the staggered 12V high-side switch, its own 5V buck, and the
    5V indicator. A3 rather than A4, because the buck now shares the page.

    The switch half is unchanged from v1. What is new is that the header's 5V
    pin comes from a LOCAL node 5V_n rather than a board-wide 5V_MAIN, so where
    that node gets its power becomes a populate choice (BUCKS/LINKS) instead of
    a layout one.
    """
    sh = S.Sheet("channel%d" % n, "Channel %d" % n, PROJECT, paper="A3", index=n + 2)
    sh.filename = "%s_channel%d.kicad_sch" % (PROJECT, n)

    RAIL, GATE, OUT_Y = 38.1, 53.34, 95.25
    V5 = "5V_%d" % n

    sh.text("Channel %d - staggered high-side switch + local 5V" % n, 38.1, 25.4, 2.54)
    sh.text("C%d1=%s with R%d1=220k sets turn-on at %s" % (n, c_gate, n, delay),
            38.1, 30.48, 1.8)
    sh.text("D%d1 clamps Vgs to 8.2V; AO3401A is rated +/-12V" % n,
            38.1, 34.29, 1.8)

    # --- 12V rail across the top
    sh.glabel("12V_MAIN", 38.1, RAIL, 180, "input")
    sh.wire((38.1, RAIL), (110.49, RAIL))

    # --- high-side P-channel switch: source on the always-on rail
    q = sh.place("Transistor_FET:AO3401A", "Q%d" % n, "AO3401A", 66.04, GATE, 180,
                 footprint=FP_SOT23, fields="left", mpn=MPN_PMOS, dkpn=DK_PMOS)
    sh.wire((63.5, RAIL), q.pin("S"))
    sh.junction((63.5, RAIL))

    # --- RC turn-on delay: C gate-source holds it off, R pulls the gate down
    c = sh.place("Device:C", "C%d1" % n, c_gate, 82.55, 45.72, footprint=c_fp,
                 mpn=c_pn[0], dkpn=c_pn[1])
    sh.wire((82.55, RAIL), c.pin("1"))
    sh.wire(c.pin("2"), (82.55, GATE))
    sh.junction((82.55, RAIL), (82.55, GATE))

    # --- Vgs clamp: cathode to source (the higher potential), anode to gate
    d = sh.place("Device:D_Zener", "D%d1" % n, "8.2V", 110.49, 45.72, 270,
                 footprint=FP_SOD123, mpn=MPN_ZENER, dkpn=DK_ZENER)
    sh.wire((110.49, RAIL), d.pin("K"))
    sh.wire(d.pin("A"), (110.49, GATE))
    sh.junction((110.49, GATE))

    sh.wire(q.pin("G"), (127.0, GATE))
    r = sh.place("Device:R", "R%d1" % n, "220k", 127.0, 62.23, footprint=FP_R0603,
                 mpn=MPN_R["220k"][0], dkpn=MPN_R["220k"][1])
    sh.wire((127.0, GATE), r.pin("1"))
    sh.wire(r.pin("2"), (127.0, 71.12))
    sh.gnd(127.0, 71.12)

    # --- per-channel overcurrent isolation, then out to the drive header
    f = sh.place("Device:Polyfuse", "F%d" % n, "2.6A/5.2A", 63.5, 72.39,
                 footprint=FP_FUSE1812, mpn=MPN_PPTC, dkpn=DK_PPTC)
    sh.wire(q.pin("D"), f.pin("1"))
    sh.wire(f.pin("2"), (63.5, OUT_Y))
    sh.wire((63.5, OUT_Y), (140.97, OUT_Y))

    # --- local decoupling at the connector
    for x, ref, val, lib, fp, pn in (
            (82.55, "C%d2" % n, "220uF/25V", "Device:C_Polarized", FP_CP_D8, CP_220U),
            (116.84, "C%d3" % n, "1uF", "Device:C", FP_C0603, C_1U)):
        cc = sh.place(lib, ref, val, x, 104.14, footprint=fp, mpn=pn[0], dkpn=pn[1])
        sh.wire((x, OUT_Y), cc.pin("1"))
        sh.wire(cc.pin("2"), (x, 113.03))
        sh.gnd(x, 113.03)
        sh.junction((x, OUT_Y))

    # --- 4x1 2.54mm header, wired out to a SATA power pigtail.
    # Pin 1 = +12V, pins 2/3 = GND, pin 4 = +5V. There is deliberately no 3.3V
    # pin, which sidesteps the PWDIS failure mode (doc section 6) by construction.
    j = sh.place("Connector_Generic:Conn_01x04", "J%d" % n, "12V/GND/GND/5V",
                 146.05, 97.79, footprint=FP_HDR4, mpn=MPN_HDR, dkpn=DK_HDR)
    sh.wire(j.pin("2"), (135.89, 97.79), (135.89, 104.14))
    sh.wire(j.pin("3"), (135.89, 100.33))
    sh.junction((135.89, 100.33))
    sh.gnd(135.89, 104.14)

    # --- 5V feed to the header, from the LOCAL node. Routed below the
    # decoupling grounds so the label stays clear.
    sh.wire(j.pin("4"), (140.97, 120.65), (101.6, 120.65))
    sh.glabel(V5, 101.6, 120.65, 180, "input")

    # --- 5V present indicator, tapped at the header end of the local node.
    # Deliberately here and not at the buck output: it then lights whether the
    # 5V came from this port's own buck or across a 0R link from a neighbour,
    # so a missing link or a dead regulator reads as one dark port.
    sh.junction((114.3, 120.65))
    led = sh.place("Device:LED", "D%d2" % n, "GRN", 114.3, 128.27, 90,
                   footprint=FP_LED0603, mpn=MPN_LED[0], dkpn=MPN_LED[1])
    sh.wire((114.3, 120.65), led.pin("A"))
    r_led = sh.place("Device:R", "R%d5" % n, "1.5k", 114.3, 140.97,
                     footprint=FP_R0603, mpn=MPN_R["1.5k"][0], dkpn=MPN_R["1.5k"][1])
    sh.wire(led.pin("K"), r_led.pin("1"))
    sh.wire(r_led.pin("2"), (114.3, 149.86))
    sh.gnd(114.3, 149.86)
    sh.text("(5 - 2.0) / 1.5k = 2.0mA", 119.38, 143.51, 1.8)

    # --- this port's own buck, to the right of the switch circuit
    buck_block(sh, n, 152.4, 0.0, BUCKS[n - 1])
    return sh


# ------------------------------------------------------------------ buck
def buck_block(sh, n, dx, dy, fitted):
    """One per-port 12V -> 5V buck, drawn into channel n's sheet at (dx, dy).

    Identical for every port -- only the refs and the output label change -- so
    "own buck" versus "neighbour's buck" is a populate choice and never a layout
    variant. When fitted is False every part here is marked DNP: the lands and
    the nets stay, the parts are not placed.

    In v1 one of these fed all five bays, which is why doc section 2's 5A target
    left the 3A TPS563200 under-rated. Here MAX_GROUP caps a buck at three
    ports, 3 x ~0.7A = 2.1A, and the same part is correctly sized.
    """
    RAIL, V5 = 53.34 + dy, 73.66 + dy
    dnp = not fitted
    tag = "" if fitted else "  [DNP - this port takes 5V from a neighbour]"

    sh.text("Port %d local 5V buck%s" % (n, tag), 38.1 + dx, 30.48 + dy, 2.54)
    sh.text("Vout = 0.768V x (1 + R%d2/R%d3) = 0.768 x (1 + 56k/10k) = 5.07V"
            % (n, n), 38.1 + dx, 35.56 + dy, 1.8)
    sh.text("Max load is a %d-port group; see BUCKS/LINKS in gen_sch.py" % MAX_GROUP,
            38.1 + dx, 39.37 + dy, 1.8)

    u = sh.place("Regulator_Switching:TPS563200", "U%d" % n, "TPS563200",
                 114.3 + dx, 76.2 + dy, footprint=FP_SOT23_6, fields="above",
                 mpn=MPN_BUCK, dkpn=DK_BUCK, dnp=dnp)

    sh.glabel("12V_MAIN", 38.1 + dx, RAIL, 180, "input")
    sh.wire((38.1 + dx, RAIL), (104.14 + dx, RAIL), u.pin("VIN"))

    for x, ref, val, fp, pn in ((46.99, "C%d4" % n, "10uF/50V", FP_C1206, C_10U),
                                (66.04, "C%d5" % n, "100nF", FP_C0603, C_100N)):
        c = sh.place("Device:C", ref, val, x + dx, 62.23 + dy, footprint=fp,
                     mpn=pn[0], dkpn=pn[1], dnp=dnp)
        sh.wire((x + dx, RAIL), c.pin("1"))
        sh.wire(c.pin("2"), (x + dx, 71.12 + dy))
        sh.gnd(x + dx, 71.12 + dy)
        sh.junction((x + dx, RAIL))

    r_en = sh.place("Device:R", "R%d4" % n, "100k", 85.09 + dx, 62.23 + dy,
                    footprint=FP_R0603, mpn=MPN_R["100k"][0],
                    dkpn=MPN_R["100k"][1], dnp=dnp)
    sh.wire((85.09 + dx, RAIL), r_en.pin("1"))
    sh.junction((85.09 + dx, RAIL))
    sh.wire(r_en.pin("2"), (85.09 + dx, 78.74 + dy), u.pin("EN"))

    sh.wire(u.pin("GND"), (114.3 + dx, 88.9 + dy))
    sh.gnd(114.3 + dx, 88.9 + dy)

    # Bootstrap cap for the high-side gate driver, SW to VBST.
    c_bst = sh.place("Device:C", "C%d6" % n, "100nF", 130.81 + dx, 82.55 + dy,
                     footprint=FP_C0603, mpn=C_100N[0], dkpn=C_100N[1], dnp=dnp)
    sh.wire(u.pin("SW"), (130.81 + dx, V5))
    sh.wire((130.81 + dx, V5), c_bst.pin("1"))
    sh.wire(u.pin("VBST"), (127.0 + dx, 76.2 + dy), (127.0 + dx, 90.17 + dy),
            (130.81 + dx, 90.17 + dy))
    sh.wire((130.81 + dx, 90.17 + dy), c_bst.pin("2"))

    l = sh.place("Device:L", "L%d" % n, "4.7uH/4.5A", 146.05 + dx, V5, 90,
                 footprint=FP_IND, mpn=MPN_L, dkpn=DK_L, dnp=dnp)
    sh.wire((130.81 + dx, V5), l.pin("1"))
    sh.junction((130.81 + dx, V5))
    sh.wire(l.pin("2"), (190.5 + dx, V5))
    sh.glabel("5V_%d" % n, 190.5 + dx, V5, 0, "output")

    # 5V_n leaves through an inductor, so KiCad ERC needs an explicit flag on
    # it -- one per port now, since each local node is its own net.
    sh.wire((163.83 + dx, V5), (163.83 + dx, 66.04 + dy))
    sh.flag(163.83 + dx, 66.04 + dy)
    sh.junction((163.83 + dx, V5))

    for x, ref in ((154.94, "C%d7" % n), (172.72, "C%d8" % n)):
        c = sh.place("Device:C", ref, "22uF/25V", x + dx, 82.55 + dy,
                     footprint=FP_C1206, mpn=C_22U[0], dkpn=C_22U[1], dnp=dnp)
        sh.wire((x + dx, V5), c.pin("1"))
        sh.wire(c.pin("2"), (x + dx, 91.44 + dy))
        sh.gnd(x + dx, 91.44 + dy)
        sh.junction((x + dx, V5))

    # Feedback divider, tapped off the 5V node right after the inductor.
    r_fbt = sh.place("Device:R", "R%d2" % n, "56k", 139.7 + dx, 99.06 + dy,
                     footprint=FP_R0603, mpn=MPN_R["56k"][0],
                     dkpn=MPN_R["56k"][1], dnp=dnp)
    r_fbb = sh.place("Device:R", "R%d3" % n, "10k", 139.7 + dx, 113.03 + dy,
                     footprint=FP_R0603, mpn=MPN_R["10k"][0],
                     dkpn=MPN_R["10k"][1], dnp=dnp)
    sh.wire((152.4 + dx, V5), (152.4 + dx, 95.25 + dy), (139.7 + dx, 95.25 + dy))
    sh.junction((152.4 + dx, V5))
    sh.wire(r_fbt.pin("2"), r_fbb.pin("1"))
    sh.wire(u.pin("VFB"), (124.46 + dx, 106.68 + dy), (139.7 + dx, 106.68 + dy))
    sh.junction((139.7 + dx, 106.68 + dy))
    sh.wire(r_fbb.pin("2"), (139.7 + dx, 121.92 + dy))
    sh.gnd(139.7 + dx, 121.92 + dy)


# ------------------------------------------------------------------ rails
def rails_sheet():
    """The 0R links between the five local 5V nodes.

    All four links live on one page on purpose: this is the sheet you read to
    see how a given build shares its bucks. Physically they sit at the column
    boundaries on the board, so schematic grouping and board grouping differ
    here -- deliberately, because the configuration is what has to be legible.

    A DNP link is still a wire as far as the netlist is concerned, so nothing
    downstream of here can catch an illegal combination. check_rails() is what
    catches it.
    """
    sh = S.Sheet("rails", "5V rail links", PROJECT, paper="A3", index=2)
    sh.filename = "%s_rails.kicad_sch" % PROJECT
    Y = 76.2

    sh.text("5V rail links - how each port gets its 5V", 38.1, 30.48, 2.54)
    for i, g in enumerate(rail_groups()):
        src = [n for n in g if BUCKS[n - 1]]
        sh.text("group %d: U%s feeds port%s %s"
                % (i + 1, src[0] if src else "?", "" if len(g) == 1 else "s",
                   ", ".join(str(n) for n in g)),
                38.1, 35.56 + i * 3.81, 1.8)
    sh.text("A link is 0R when fitted and simply absent when not. Fitting a link "
            "between two populated bucks", 38.1, 55.88, 1.8)
    sh.text("parallels them, and verify.py check 5 refuses that configuration.",
            38.1, 59.69, 1.8)

    X = [38.1 + 50.8 * i for i in range(5)]      # one column per port
    for n, x in enumerate(X, start=1):
        sh.glabel("5V_%d" % n, x, Y, 180 if n == 1 else 0, "bidirectional")

    for i, fitted in enumerate(LINKS, start=1):
        xm = (X[i - 1] + X[i]) / 2.0
        r = sh.place("Device:R", "R6%d" % i, "0R", xm, Y, 90,
                     footprint=FP_R1206, mpn=MPN_R0[0], dkpn=MPN_R0[1],
                     dnp=not fitted)
        sh.wire((X[i - 1], Y), r.pin("1"))
        sh.wire(r.pin("2"), (X[i], Y))
        sh.text("R6%d %s" % (i, "fitted" if fitted else "OPEN"),
                xm - 8.89, Y - 7.62, 1.8)
    return sh


# ------------------------------------------------------------------ input
def input_sheet():
    sh = S.Sheet("input", "Input protection", PROJECT, index=1)
    sh.filename = "%s_input.kicad_sch" % PROJECT
    RAIL = 60.96

    sh.text("Input protection - 12V brick, fuse, reverse-polarity guard, bulk C",
            38.1, 34.29, 2.54)

    j = sh.place("Connector:Barrel_Jack", "J8", "12V DC 8-10A", 55.88, 63.5,
                 footprint=FP_JACK, mpn=MPN_JACK, dkpn=DK_JACK)
    # Two FC-203-22 clips hold one 5x20mm 10A cartridge fuse (fuse ordered separately).
    f = sh.place("Device:Fuse", "F8", "10A fast-blow", 76.2, RAIL, 90,
                 footprint=FP_FUSEHOLDER, mpn=MPN_CLIP, dkpn=DK_CLIP)
    sh.wire(j.pin("1"), f.pin("1"))
    sh.wire(j.pin("2"), (63.5, 74.93))
    sh.gnd(63.5, 74.93)

    # Reverse-polarity guard: body diode faces the load, gate to GND, so the
    # FET only enhances when the input polarity is correct.
    # Q8 carries the whole board (~5.1A steady incl. the buck), so it needs a
    # bigger package than the SOT-23 used per channel: 1.6W vs 0.39W.
    q = sh.place("sata_psu:AOD4185", "Q8", "AOD4185", 95.25, 63.5, 90,
                 footprint=FP_TO252, fields="above", mpn=MPN_PMOS8, dkpn=DK_PMOS8)
    sh.wire(f.pin("2"), q.pin("D"))
    sh.wire(q.pin("G"), (95.25, 74.93))
    sh.gnd(95.25, 74.93)

    sh.wire(q.pin("S"), (200.66, RAIL))
    sh.glabel("12V_MAIN", 200.66, RAIL, 0, "output")

    sh.wire((110.49, RAIL), (110.49, 53.34))
    sh.flag(110.49, 53.34)
    sh.junction((110.49, RAIL))

    for x, ref, val, lib, fp, pn in (
            (121.92, "C81", "1000uF/25V", "Device:C_Polarized", FP_CP_D10, CP_1000U),
            (146.05, "C82", "1000uF/25V", "Device:C_Polarized", FP_CP_D10, CP_1000U),
            (170.18, "C83", "10uF/50V", "Device:C", FP_C1206, C_10U)):
        c = sh.place(lib, ref, val, x, 69.85, footprint=fp, mpn=pn[0], dkpn=pn[1])
        sh.wire((x, RAIL), c.pin("1"))
        sh.wire(c.pin("2"), (x, 78.74))
        sh.gnd(x, 78.74)
        sh.junction((x, RAIL))

    # 12V present indicator. Deliberately tapped AFTER Q8, not at the jack:
    # it then also proves the reverse-polarity guard is conducting, and "jack
    # lit but nothing works" is a different fault from "nothing lit at all".
    # Note this shows the COMMON rail, so it lights before any channel switches
    # on -- it says nothing about the stagger.
    sh.junction((185.42, RAIL))
    led = sh.place("Device:LED", "D81", "GRN", 185.42, 69.85, 90,
                   footprint=FP_LED0603, mpn=MPN_LED[0], dkpn=MPN_LED[1])
    sh.wire((185.42, RAIL), led.pin("A"))
    r_led = sh.place("Device:R", "R81", "4.7k", 185.42, 82.55, footprint=FP_R0603,
                     mpn=MPN_R["4.7k"][0], dkpn=MPN_R["4.7k"][1])
    sh.wire(led.pin("K"), r_led.pin("1"))
    sh.wire(r_led.pin("2"), (185.42, 91.44))
    sh.gnd(185.42, 91.44)
    sh.text("(12 - 2.0) / 4.7k = 2.1mA", 190.5, 85.09, 1.8)

    # Star ground reference for the whole board (doc section 7).
    sh.flag(78.74, 86.36)
    sh.wire((78.74, 86.36), (78.74, 91.44))
    sh.gnd(78.74, 91.44)
    sh.text("Star ground: single point back to the brick negative", 66.04, 99.06, 1.8)
    return sh


# ------------------------------------------------------------------ assemble
def main():
    os.makedirs(OUT, exist_ok=True)
    # Build the project symbol library first: the AO4407A symbol carries
    # the SO-8 pad numbering that the generic Device:Q_PMOS lacks.
    make_symbols.main()
    errs = check_rails()
    if errs:
        raise SystemExit("illegal BUCKS/LINKS configuration:\n  "
                         + "\n  ".join(errs))
    subs = [input_sheet(), rails_sheet()]
    subs += [channel_sheet(n, c, d, fp, pn) for n, c, d, fp, pn in CHANNELS]

    root = S.Sheet("root", "5-Bay SATA Drive Power Supply", PROJECT)
    root.filename = "%s.kicad_sch" % PROJECT
    root.text("5-Bay SATA Drive Power Supply", 38.1, 25.4, 3.5)
    root.text("Single 12V brick, five analog-staggered channels, per-port 5V buck",
              38.1, 31.75, 2.0)
    root.text("5V rails: " + " | ".join(
        "U%s -> port%s %s" % ([n for n in g if BUCKS[n - 1]][0] if any(
            BUCKS[n - 1] for n in g) else "?", "" if len(g) == 1 else "s",
            ",".join(str(n) for n in g)) for g in rail_groups()),
        38.1, 36.83, 1.8)

    boxes = [(25.4, 44.45), (25.4, 88.9), (114.3, 44.45), (114.3, 88.9),
             (114.3, 133.35), (190.5, 44.45), (190.5, 88.9)]
    refs = [S.SheetRef(s, x, y, 63.5, 25.4, str(i + 2))
            for i, (s, (x, y)) in enumerate(zip(subs, boxes))]

    with open(os.path.join(OUT, root.filename), "w", encoding="utf-8") as fh:
        fh.write(S.render(root, root.uuid, None, refs))
    for s, r in zip(subs, refs):
        with open(os.path.join(OUT, s.filename), "w", encoding="utf-8") as fh:
            fh.write(S.render(s, root.uuid, r.uuid))

    print("root + %d sub-sheets written to %s/" % (len(subs), OUT))
    missing = [c.ref for s in subs for c in s.comps
               if not c.footprint and not c.lib_id.startswith("power:")]
    print("symbols without a footprint: %s" % (missing or "none"))


if __name__ == "__main__":
    main()
