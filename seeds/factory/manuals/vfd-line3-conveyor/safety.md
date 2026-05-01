---
title: PowerFlex 525 Safety and Lockout-Tagout
asset_id: vfd-line3-conveyor
brand: Allen-Bradley
model: PowerFlex 525
section: safety
---

# PowerFlex 525 Safety and Lockout-Tagout (LOTO)

## Hazard Summary

- Hazardous voltage: terminals R/L1, S/L2, T/L3 carry 480 VAC.
- Stored energy: DC bus capacitors retain charge for at least 5 minutes
  after disconnect.
- Rotating machinery: the conveyor belt downstream of this drive can crush
  fingers and entangle clothing.

## Required PPE

- Class 0 rubber insulating gloves (1000 V rating).
- Arc-rated face shield meeting ATPV 8 cal/cm² minimum for the panel.
- Steel-toed boots and high-visibility vest while on the line floor.

## Lockout-Tagout Procedure

1. Notify the line supervisor and stop production via the Cell B HMI E-stop.
2. Open the upstream disconnect labelled **DS-LINE3-A** in MCC-2.
3. Apply your padlock and danger tag; record the asset_id
   `vfd-line3-conveyor` on the LOTO log.
4. Wait at least **5 minutes** for the DC bus to discharge.
5. Verify zero energy at terminals R/L1, S/L2, T/L3 with a properly rated
   meter, on a known-live source first, then on the drive, then on the
   known-live source again (the **live-dead-live** test).
6. Only after a successful zero-energy verification may you open the panel.

## Restoring to Service

1. Close all panel covers and confirm no tools remain inside.
2. Remove your LOTO and tag in reverse order.
3. Reset the drive faults from the HIM and run a no-load jog before
   resuming production.
