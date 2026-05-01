---
title: Siemens S7-1200 Diagnostics
asset_id: plc-cellb-main
brand: Siemens
model: SIMATIC S7-1200
section: troubleshooting
---

# Siemens S7-1200 Diagnostics

## Status LEDs

| LED | Color | Meaning |
|-----|-------|---------|
| RUN | green | CPU is in RUN mode |
| STOP| yellow | CPU is in STOP mode |
| SF  | red | System fault detected |
| BF  | red | PROFINET bus fault |
| MAINT| yellow | Maintenance required |

## SF Solid Red — System Fault

Indicates a CPU diagnostic fault. Connect to the CPU with TIA Portal and read the diagnostic buffer.

Common causes:

1. CPU watchdog timeout. Reduce scan time by moving large data block initializations to OB100.
2. I/O module reported a wire-break on a 4..20 mA channel. Inspect channel wiring.
3. Battery-backed retentive memory CRC failure. Recharge or replace the CPU memory card.

Recovery procedure:

1. Read diagnostic buffer in TIA Portal (`Online & diagnostics > Diagnostics buffer`).
2. Address the most recent entry first; entries are timestamped.
3. Cycle the CPU to RUN once the underlying cause is cleared.

## BF Solid Red — PROFINET Bus Fault

The CPU has lost cyclic communication with one or more PROFINET devices.

Recovery procedure:

1. Inspect the PROFINET cable and connector at the affected device.
2. Verify the device LEDs on the IO-device.
3. From TIA Portal, run `Online & diagnostics > Topology` to identify the
   broken link.
4. Replace the cable or connector if intermittent.
