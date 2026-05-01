---
title: ABB ACS580 Fault Codes and Recovery
asset_id: vfd-line2-pump
brand: ABB
model: ACS580
section: troubleshooting
---

# ABB ACS580 Fault Codes and Recovery

## Fault F0001 — Overcurrent

The output current exceeded the internal hardware limit, typically during
a cold start of the Line 2 transfer pump.

Recovery procedure:

1. Confirm the pump shaft turns freely by hand (after LOTO).
2. Increase the start ramp time in parameter `23.12 Acceleration time 1`
   from 5.0 s to 10.0 s.
3. Verify the motor cable shield is bonded at both ends.
4. Reset the fault from the assistant control panel.

Likely failed parts:

- Pump impeller (mechanical bind)
- Output IGBT module (kit `BIGBT-580-11`)

## Fault F0002 — DC Overvoltage

The DC link voltage exceeded 800 V, typically from regenerative braking.

Recovery procedure:

1. Lengthen `23.13 Deceleration time 1` by 25%.
2. If a brake chopper is installed, verify resistor wiring on R+, R−.
3. Reset the fault.

## Fault F0007 — Motor Overtemperature

PTC input registered an over-temperature.

Recovery procedure:

1. Allow the motor to cool 15 minutes minimum.
2. Confirm cooling fan rotation.
3. Reset and run at reduced load to verify recovery.
