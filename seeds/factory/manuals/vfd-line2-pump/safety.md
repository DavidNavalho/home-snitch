---
title: ABB ACS580 Safety and Lockout-Tagout
asset_id: vfd-line2-pump
brand: ABB
model: ACS580
section: safety
---

# ABB ACS580 Safety and Lockout-Tagout (LOTO)

## Hazards

- 480 VAC at input terminals U1, V1, W1.
- DC bus capacitors hold dangerous voltage for 5 minutes after disconnect.
- The Line 2 transfer pump is a rotating, pressurized system; trapped
  fluid in the discharge pipe can spray under pressure.

## Required PPE

- Class 0 1000 V rubber insulating gloves with leather protectors.
- Arc-rated coverall (min 8 cal/cm²).
- Splash goggles when working on the pump volute or piping.

## LOTO Procedure

1. Stop the pump from the operator station.
2. Open and lock disconnect **DS-LINE2-PUMP** at MCC-2.
3. Bleed the pump discharge through the test port to relieve pressure.
4. Apply LOTO tag with asset_id `vfd-line2-pump`.
5. Wait 5 minutes; verify zero energy at U1, V1, W1 with the live-dead-live test.
