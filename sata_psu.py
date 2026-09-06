"""
5-Channel SATA Drive Power Supply -- SKiDL circuit description.

REFERENCE NETLIST ONLY. The schematic itself is drawn by gen_sch.py; this file
exists as an INDEPENDENT description of the same circuit, so verify.py can diff
the two and prove the drawn geometry connects what the design intends.
SKiDL's own schematic output is not used -- its force-directed placer stacked
symbols on top of each other -- so generate_schematic() is deliberately absent.

Topology (v2):
  12V brick -> fuse -> reverse-polarity PMOS -> 12V_MAIN (always on) + 12V LED
  12V_MAIN  -> per-port TPS563200 buck -> that port's local 5V_n + 5V LED
  5V_n      -> 0R link -> 5V_n+1, so one buck can feed its neighbours
  12V_MAIN  -> 5x RC-staggered high-side PMOS -> polyfuse -> 4x1 header

Per-channel stagger comes solely from C_gate (R fixed at 220k), per doc section 4.

BUCKS/LINKS below must mirror gen_sch.py -- they are two descriptions of the
same board, and verify.py exists to prove they agree. Note that every buck and
every link is INSTANTIATED here whatever its populate flag: a DNP part is still
a part on the board and still a wire in the netlist, so the netlists must match
regardless of which are fitted. Which ones may be fitted is a separate question,
and gen_sch.check_rails() is what answers it.
"""
import os

os.environ["KICAD9_SYMBOL_DIR"] = r"D:\Kicad\share\kicad\symbols"

from skidl import (
    Part, Net, TEMPLATE, subcircuit, generate_netlist, generate_schematic,
    generate_svg, ERC, set_default_tool, KICAD9, POWER,
)

set_default_tool(KICAD9)

# ---------------------------------------------------------------- templates
R      = Part("Device", "R",           dest=TEMPLATE)
C      = Part("Device", "C",           dest=TEMPLATE)
CP     = Part("Device", "C_Polarized", dest=TEMPLATE)
L      = Part("Device", "L",           dest=TEMPLATE)
PMOS   = Part("Device", "Q_PMOS",      dest=TEMPLATE)
ZENER  = Part("Device", "D_Zener",     dest=TEMPLATE)
LED    = Part("Device", "LED",         dest=TEMPLATE)
PFUSE  = Part("Device", "Polyfuse",    dest=TEMPLATE)
FUSE   = Part("Device", "Fuse",        dest=TEMPLATE)
CONN4  = Part("Connector_Generic", "Conn_01x04", dest=TEMPLATE)
JACK   = Part("Connector", "Barrel_Jack",        dest=TEMPLATE)

# ---------------------------------------------------------------- global nets
# Mark the rails as power sources so ERC does not flag the POWER-IN pins
# on U1 as undriven.
gnd      = Net("GND");      gnd.drive      = POWER
v12_main = Net("12V_MAIN"); v12_main.drive = POWER
# One local 5V node per port; they are joined only through the 0R links, so
# they stay five distinct nets in the netlist however the board is populated.
v5 = {}
for _n in range(1, 6):
    v5[_n] = Net("5V_%d" % _n)
    v5[_n].drive = POWER


# ================================================================ input stage
@subcircuit
def input_protection(v_in_raw, v12, gnd):
    """Barrel jack -> 10A fuse -> reverse-polarity PMOS -> bulk caps."""
    j = JACK(ref="J0", value="12V_DC_8-10A")
    j[1] += v_in_raw          # centre pin, +12V
    j[2] += gnd

    f = FUSE(ref="F0", value="10A_fast")
    v_fused = Net("12V_FUSED")
    f[1, 2] += v_in_raw, v_fused

    # Reverse-polarity guard: PMOS in the high side, body diode facing the load.
    # Source to the load side, drain to the source rail, gate to GND -- so the
    # FET only enhances when the input polarity is correct.
    q = PMOS(ref="Q0", value="PMOS_reverse_polarity")
    q["S"] += v12
    q["D"] += v_fused
    q["G"] += gnd

    # Bulk input capacitance (doc section 3: 2x1000uF + 10uF ceramic)
    for i in (1, 2):
        cb = CP(ref=f"C_BULK{i}", value="1000uF/25V")
        cb[1, 2] += v12, gnd
    chf = C(ref="C_IN_HF", value="10uF")
    chf[1, 2] += v12, gnd

    # 12V present indicator, tapped after the guard FET so it also proves the
    # guard is conducting. Common rail: it says nothing about the stagger.
    d_led = LED(ref="D_LED12", value="GRN")
    r_led = R(ref="R_LED12", value="4.7k")
    k = Net("LED12_K")
    d_led["A"] += v12
    d_led["K"] += k
    r_led[1, 2] += k, gnd


# ================================================================ 5V buck
@subcircuit
def buck_5v(v12, v_out, gnd, n):
    """One per-port TPS563200 synchronous buck, 12V -> 5V, for port n.

    In v1 a single one of these fed all five bays against doc section 2's 5A
    target, which left the 3A part under-rated. Per port, with sharing capped
    at a three-port group (gen_sch.MAX_GROUP), the worst case is 3 x ~0.7A =
    2.1A and the same part is correctly sized.

    Vout = Vref * (1 + R_fbt/R_fbb), Vref = 0.768V
         = 0.768 * (1 + 56k/10k) = 5.07V
    L = (Vin-Vout)*Vout / (Vin * fsw * I_ripple)
      = (12-5)*5 / (12 * 580kHz * 0.9A) = 5.6uH -> 4.7uH standard value
    """
    u = Part("Regulator_Switching", "TPS563200", ref=f"U_B{n}", value="TPS563200")
    sw   = Net(f"SW{n}")
    vbst = Net(f"VBST{n}")
    vfb  = Net(f"VFB{n}")

    u["VIN"]  += v12
    u["GND"]  += gnd
    u["SW"]   += sw
    u["VBST"] += vbst
    u["VFB"]  += vfb

    # EN: pull high to VIN to enable.
    r_en = R(ref=f"R_EN{n}", value="100k")
    r_en[1, 2] += v12, u["EN"]

    # Input decoupling, close to the IC. This loop is the noise source and
    # there are now five of them, one beside each drive connector.
    c_in = C(ref=f"C_BIN{n}", value="10uF/25V")
    c_in[1, 2] += v12, gnd
    c_in_hf = C(ref=f"C_BINHF{n}", value="100nF")
    c_in_hf[1, 2] += v12, gnd

    # Bootstrap cap for the high-side gate driver.
    c_bst = C(ref=f"C_BST{n}", value="100nF")
    c_bst[1, 2] += sw, vbst

    # Output inductor.
    l_out = L(ref=f"L_B{n}", value="4.7uH/5A")
    l_out[1, 2] += sw, v_out

    # Output capacitance.
    for suffix in ("A", "B"):
        c_out = C(ref=f"C_BOUT{n}{suffix}", value="22uF/10V")
        c_out[1, 2] += v_out, gnd

    # Feedback divider: 5.07V out.
    r_fbt = R(ref=f"R_FBT{n}", value="56k")
    r_fbb = R(ref=f"R_FBB{n}", value="10k")
    r_fbt[1, 2] += v_out, vfb
    r_fbb[1, 2] += vfb, gnd


# ================================================================ one channel
@subcircuit
def sata_channel(v12, v5_local, gnd, index, c_gate):
    """One RC-staggered high-side switch feeding a 4x1 drive header.

    R is fixed at 220k across all channels; c_gate alone sets the stagger,
    per the table in doc section 4.
    """
    n = index
    v12_ch  = Net(f"12V_CH{n}")
    v12_out = Net(f"12V_CH{n}_OUT")
    gate    = Net(f"GATE{n}")

    # High-side P-channel switch: source on the always-on rail.
    q = PMOS(ref=f"Q{n}", value="PMOS_4A_lowRdson")
    q["S"] += v12
    q["D"] += v12_ch
    q["G"] += gate

    # RC turn-on delay. R pulls the gate down (towards on); C from gate to
    # source holds it off at power-up and sets the time constant.
    r_g = R(ref=f"R{n}", value="220k")     # -> R{n}1 in the drawing
    r_g[1, 2] += gate, gnd
    c_g = C(ref=f"C{n}", value=c_gate)
    c_g[1, 2] += gate, v12

    # Vgs clamp so the gate never exceeds its rating off the 12V rail.
    # Cathode to source (the higher potential), anode to gate.
    dz = ZENER(ref=f"D{n}", value="10V")
    dz["K"] += v12
    dz["A"] += gate

    # Per-channel overcurrent isolation.
    pf = PFUSE(ref=f"F{n}", value="2.6A_hold/5.2A_trip")
    pf[1, 2] += v12_ch, v12_out

    # Local decoupling at the connector.
    c_bulk = CP(ref=f"C_LOC{n}", value="220uF/25V")
    c_bulk[1, 2] += v12_out, gnd
    c_hf = C(ref=f"C_LOC{n}_HF", value="1uF")
    c_hf[1, 2] += v12_out, gnd

    # 4x1 2.54mm header -> SATA power pigtail.
    # Pin 1 = +12V, pins 2/3 = GND, pin 4 = +5V.
    # No 3.3V pin exists by construction, which sidesteps PWDIS (doc section 6).
    j = CONN4(ref=f"J{n}", value="12V/GND/GND/5V")
    j[1] += v12_out
    j[2] += gnd
    j[3] += gnd
    j[4] += v5_local

    # 5V present indicator, on the LOCAL node at the header end -- so it lights
    # whether this port's 5V came from its own buck or across a link from a
    # neighbour. A dead regulator or a missing link reads as one dark port.
    d_led = LED(ref=f"D_LED{n}", value="GRN")
    r_led = R(ref=f"R_LED{n}", value="1.5k")
    k = Net(f"LED{n}_K")
    d_led["A"] += v5_local
    d_led["K"] += k
    r_led[1, 2] += k, gnd


# ================================================================ top level
v_in_raw = Net("12V_IN_RAW")

# KiCad's ERC (unlike SKiDL's) needs an explicit PWR_FLAG on any rail that is
# not fed by a regulator OUTPUT pin. 12V_MAIN comes in from a barrel jack and
# 5V_MAIN leaves U1 through an inductor, so both look undriven without these.
PWR_FLAG = Part("power", "PWR_FLAG", dest=TEMPLATE)
for _flag_net in [gnd, v12_main] + [v5[_n] for _n in range(1, 6)]:
    PWR_FLAG(ref=f"#FLG_{_flag_net.name}")[1] += _flag_net

input_protection(v_in_raw, v12_main, gnd)

# Stagger table from doc section 4: R fixed, C sets the delay.
STAGGER = ["1uF", "2.2uF", "4.7uF", "10uF", "22uF"]
for i, c_val in enumerate(STAGGER, start=1):
    buck_5v(v12_main, v5[i], gnd, i)
    sata_channel(v12_main, v5[i], gnd, i, c_val)

# The 0R rail links, R61..R64 in the drawing. Every one is instantiated; which
# are actually fitted is gen_sch.LINKS, and it does not change the netlist.
for i in range(1, 5):
    r_link = R(ref=f"R_LINK{i}", value="0R")
    r_link[1, 2] += v5[i], v5[i + 1]

if __name__ == "__main__":
    ERC()
    generate_netlist(file_="kicad/reference.net")
