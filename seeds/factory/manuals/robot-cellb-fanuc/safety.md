---
title: Fanuc R-30iB Cell B Safety
asset_id: robot-cellb-fanuc
brand: Fanuc
model: R-30iB Plus
section: safety
---

# Fanuc R-30iB Cell B Safety

## Hazards

- The robot can move at up to 2 m/s in AUTO mode. Stay outside the work
  envelope (yellow floor markings) when the cell is energized.
- The end-of-arm gripper carries 25 kg payloads; pinch and crush hazards
  exist between gripper and fixture nests.

## Required PPE

- Hard hat and safety glasses inside the cell footprint.
- Steel-toed boots.
- High-visibility vest near the conveyor.

## LOTO Procedure (entering the work envelope)

1. Place Cell B HMI to **Maintenance** mode.
2. Press the cell entry E-stop and verify SRVO-001 on the teach pendant.
3. Open the safety door; verify the door interlock latches in OFF.
4. Hang LOTO tag on the safety door clasp using asset_id
   `robot-cellb-fanuc`.
5. Use the teach pendant in T1 (manual reduced) mode for any movement
   while inside the cell, with a second person at the operator station.
