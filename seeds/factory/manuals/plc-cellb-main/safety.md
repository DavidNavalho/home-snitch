---
title: S7-1200 Cell B Safety and Lockout-Tagout
asset_id: plc-cellb-main
brand: Siemens
model: SIMATIC S7-1200
section: safety
---

# S7-1200 Cell B Safety and Lockout-Tagout

## Hazards

- 24 VDC supply on the CPU is low energy, but the CPU controls the
  Cell B robot and conveyor — losing visibility on its outputs while
  the cell is energized is unsafe.
- The CPU enclosure shares MCC-2 with 480 VAC drives; treat the panel
  as live until LOTO is verified.

## Required PPE

- Class 0 rubber insulating gloves when working in MCC-2.
- Arc-rated face shield for any panel work above 50 V.
- ESD wrist strap when handling the CPU module.

## LOTO Procedure

1. Place the Cell B HMI to **Maintenance** mode.
2. Open and lock disconnect **DS-CELLB-MAIN** at MCC-2.
3. Verify the CPU LEDs go dark (no LED illumination).
4. Apply tag with asset_id `plc-cellb-main`.
5. Live-dead-live test on the 24 VDC bus before touching wiring.
