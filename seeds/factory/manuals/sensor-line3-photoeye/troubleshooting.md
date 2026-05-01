---
title: SICK W4-3 Laser Photoelectric Troubleshooting
asset_id: sensor-line3-photoeye
brand: SICK
model: W4-3 Laser
section: troubleshooting
---

# SICK W4-3 Laser Photoelectric Troubleshooting

## Status Indicators

| LED | Color | Meaning |
|-----|-------|---------|
| Q   | yellow | Output is active (target detected) |
| Stab| green | Stable signal margin |
| Warn| orange | Marginal signal — clean lens |
| Err | red | No usable return signal |

## Orange "Warn" — Signal Marginal

Recovery procedure:

1. Wipe the emitter and receiver lenses with a microfiber cloth and
   isopropyl alcohol.
2. Verify the reflector is square to the sensor face.
3. Re-teach the background suppression with the empty conveyor.

## Red "Err" — No Signal

Recovery procedure:

1. Confirm 24 VDC at the M12 connector pin 1.
2. Verify the reflector tape is intact and not water-damaged.
3. Realign the sensor; the dot of red laser light must hit the center of
   the reflector.
4. If the LED stays red after realignment, replace the sensor body
   (part `WL4-3F2230`).
