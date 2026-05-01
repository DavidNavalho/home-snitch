---
title: SICK W4-3 Safety
asset_id: sensor-line3-photoeye
brand: SICK
model: W4-3 Laser
section: safety
---

# SICK W4-3 Safety

## Laser Class

The W4-3 emits a Class 1 visible red laser, eye-safe under all viewing
conditions of normal use. Do not view the emitter through magnifying optics.

## LOTO Note

The sensor itself runs on 24 VDC and is supplied from the Cell B I/O
distribution block. Lock out the Cell B PLC supply (`plc-cellb-main`,
disconnect `DS-CELLB-MAIN`) before disconnecting the M12 cable on a live
production line, to avoid spurious Q outputs to upstream logic.

## PPE

Standard safety glasses are sufficient.
