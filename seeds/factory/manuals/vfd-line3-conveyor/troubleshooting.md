---
title: PowerFlex 525 Troubleshooting and Fault Codes
asset_id: vfd-line3-conveyor
brand: Allen-Bradley
model: PowerFlex 525
section: troubleshooting
---

# PowerFlex 525 Troubleshooting and Fault Codes

## Reading Faults

The HIM display shows the active fault as `Fxxx`. Press **Esc** to view the
fault queue. The most recent five faults are stored in F1..F5 of parameter
P951.

## Fault F004 — UnderVoltage

The bus voltage fell below the brownout threshold (default 90% of nominal).

Likely causes:

- Sag on the incoming three-phase mains during a heavy in-rush event on Line 3.
- Loose wiring on terminals R/L1, S/L2, T/L3.
- Failing pre-charge resistor on the DC bus.

Recovery procedure:

1. Verify mains voltage with a meter at the input terminals; expect 480 VAC ±10%.
2. Reset the fault by pressing **Stop** twice on the HIM.
3. If the fault repeats within 30 minutes, schedule maintenance to inspect
   the pre-charge resistor and DC bus capacitors.

Likely failed parts:

- Pre-charge resistor (Allen-Bradley part 25-PCHG-A1)
- DC bus capacitor bank (refer to capacitor service kit 25-CAPKIT-7P5)

## Fault F005 — OverVoltage

The DC bus rose above the trip level, usually during deceleration of a high
inertia load.

Recovery procedure:

1. Increase decel time in parameter P040 by 25%.
2. If a dynamic brake resistor is installed, verify its wiring at terminals
   DC+ and BR; check the brake transistor with a continuity meter.
3. Reset the fault.

## Fault F007 — Motor Overload

The drive integrated I²t calculation exceeded the motor thermal limit.

Recovery procedure:

1. Allow the motor to cool for at least 10 minutes.
2. Check the conveyor belt for jams or debris.
3. Verify the motor nameplate FLA matches parameter P033.
4. Reset by cycling power or pressing **Stop** twice.

Likely failed parts:

- Motor bearings (if a mechanical bind preceded the trip)
- Conveyor belt tensioner

## Fault F012 — HW OverCurrent

The drive output exceeded 200% of rated current for one cycle. Indicates a
short on the load side or a failing IGBT module.
