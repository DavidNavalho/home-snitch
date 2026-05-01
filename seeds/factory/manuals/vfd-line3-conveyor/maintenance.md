---
title: PowerFlex 525 Preventive Maintenance Schedule
asset_id: vfd-line3-conveyor
brand: Allen-Bradley
model: PowerFlex 525
section: preventive-maintenance
---

# PowerFlex 525 Preventive Maintenance Schedule

## Daily Checks (every shift)

- Confirm the heatsink fan is running and free of debris.
- Verify HIM shows `Ready` and no fault is queued.
- Listen for unusual whining or buzzing from the drive enclosure.

## Weekly Checks

- Vacuum the drive vents; do not use compressed air, which can drive dust
  into the IGBT module.
- Check torque on power terminals R/L1, S/L2, T/L3 to 35 lb-in.
- Verify the cabinet door gasket seals fully and the IP rating is intact.

## Quarterly Checks

- Reform the DC bus capacitors if the drive has been idle for more than
  a month: power up at no load for 30 minutes.
- Replace the drive cooling fan kit (part 25-FAN-FRAME-D) every 3 years,
  or sooner if dust accumulation is heavy.
- Run parameter file backup via the AppView USB port. Compare to the
  baseline file in the maintenance vault.

## Replacement Parts to Stock

- Cooling fan kit `25-FAN-FRAME-D`
- Pre-charge resistor `25-PCHG-A1`
- Capacitor service kit `25-CAPKIT-7P5`
- HIM keypad `22-HIM-A3`
