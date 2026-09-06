"""
5-Channel SATA Drive Power Supply -- SKiDL circuit description.

REFERENCE NETLIST ONLY. The schematic itself is drawn by gen_sch.py; this file
exists as an INDEPENDENT description of the same circuit, so verify.py can diff
the two and prove the drawn geometry connects what the design intends.
SKiDL's own schematic output is not used -- its force-directed placer stacked
symbols on top of each other -- so generate_schematic() is deliberately absent.

Topology:
  12V brick -> fuse -> reverse-polarity PMOS -> 12V_MAIN (always on)
  12V_MAIN  -> TPS563200 buck -> 5V_MAIN (always on, feeds all bays)
  12V_MAIN  -> 5x RC-staggered high-side PMOS -> polyfuse -> 4x1 header

Per-channel stagger comes solely from C_gate (R fixed at 220k), per doc section 4.
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
PFUSE  = Part("Device", "Polyfuse",    dest=TEMPLATE)
FUSE   = Part("Device", "Fuse",        dest=TEMPLATE)
CONN4  = Part("Connector_Generic", "Conn_01x04", dest=TEMPLATE)
JACK   = Part("Connector", "Barrel_Jack",        dest=TEMPLATE)

# ---------------------------------------------------------------- global nets
# Mark the rails as power sources so ERC does not flag the POWER-IN pins
# on U1 as undriven.
gnd      = Net("GND");      gnd.drive      = POWER
v12_main = Net("12V_MAIN"); v12_main.drive = POWER
v5_main  = Net("5V_MAIN");  v5_main.drive  = POWER


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


# ================================================================ 5V buck
@subcircuit
def buck_5v(v12, v5, gnd):
    """TPS563200 synchronous buck, 12V -> 5V.

    NOTE: TPS563200 is rated 3A. Doc section 2 targets a 5A 5V rail. This part
    is UNDER-RATED for that target and is placed here as a pin-compatible
    stand-in pending the final regulator choice (see section 10).

    Vout = Vref * (1 + R_fbt/R_fbb), Vref = 0.768V
         = 0.768 * (1 + 56k/10k) = 5.07V
    L = (Vin-Vout)*Vout / (Vin * fsw * I_ripple)
      = (12-5)*5 / (12 * 580kHz * 0.9A) = 5.6uH -> 4.7uH standard value
    """
    u = Part("Regulator_Switching", "TPS563200", ref="U1", value="TPS563200")
    sw   = Net("SW")
    vbst = Net("VBST")
    vfb  = Net("VFB")

    u["VIN"]  += v12
    u["GND"]  += gnd
    u["SW"]   += sw
    u["VBST"] += vbst
    u["VFB"]  += vfb

    # EN: pull high to VIN to enable.
    r_en = R(ref="R_EN", value="100k")
    r_en[1, 2] += v12, u["EN"]

    # Input decoupling, close to the IC.
    c_in = C(ref="C_BUCK_IN", value="10uF/25V")
    c_in[1, 2] += v12, gnd
    c_in_hf = C(ref="C_BUCK_IN_HF", value="100nF")
    c_in_hf[1, 2] += v12, gnd

    # Bootstrap cap for the high-side gate driver.
    c_bst = C(ref="C_BST", value="100nF")
    c_bst[1, 2] += sw, vbst

    # Output inductor.
    l_out = L(ref="L1", value="4.7uH/5A")
    l_out[1, 2] += sw, v5

    # Output capacitance.
    for i in (1, 2):
        c_out = C(ref=f"C_BUCK_OUT{i}", value="22uF/10V")
        c_out[1, 2] += v5, gnd

    # Feedback divider: 5.07V out.
    r_fbt = R(ref="R_FBT", value="56k")
    r_fbb = R(ref="R_FBB", value="10k")
    r_fbt[1, 2] += v5, vfb
    r_fbb[1, 2] += vfb, gnd


# ================================================================ one channel
@subcircuit
def sata_channel(v12, v5, gnd, index, c_gate):
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
    r_g = R(ref=f"R{n}", value="220k")
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
    j[4] += v5


# ================================================================ top level
v_in_raw = Net("12V_IN_RAW")

# KiCad's ERC (unlike SKiDL's) needs an explicit PWR_FLAG on any rail that is
# not fed by a regulator OUTPUT pin. 12V_MAIN comes in from a barrel jack and
# 5V_MAIN leaves U1 through an inductor, so both look undriven without these.
PWR_FLAG = Part("power", "PWR_FLAG", dest=TEMPLATE)
for _flag_net in (gnd, v12_main, v5_main):
    PWR_FLAG(ref=f"#FLG_{_flag_net.name}")[1] += _flag_net

input_protection(v_in_raw, v12_main, gnd)
buck_5v(v12_main, v5_main, gnd)

# Stagger table from doc section 4: R fixed, C sets the delay.
STAGGER = ["1uF", "2.2uF", "4.7uF", "10uF", "22uF"]
for i, c_val in enumerate(STAGGER, start=1):
    sata_channel(v12_main, v5_main, gnd, i, c_val)

if __name__ == "__main__":
    ERC()
    generate_netlist(file_="kicad/reference.net")
