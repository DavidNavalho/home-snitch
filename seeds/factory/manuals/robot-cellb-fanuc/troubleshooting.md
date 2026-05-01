---
title: Fanuc R-30iB Plus Alarm Codes
asset_id: robot-cellb-fanuc
brand: Fanuc
model: R-30iB Plus
section: troubleshooting
---

# Fanuc R-30iB Plus Alarm Codes

## SRVO-001 Operator Panel E-stop

The operator panel emergency stop button is depressed.

Recovery procedure:

1. Verify there is no person, tool, or fixture inside the Cell B work
   envelope.
2. Reset the Cell B HMI to acknowledge the safety event log.
3. Twist the operator panel E-stop pushbutton to release.
4. Press **RESET** on the teach pendant.
5. Press **CYCLE START** at the operator station.

## SRVO-002 Teach Pendant E-stop

The teach pendant E-stop is depressed. Same recovery sequence as
SRVO-001 but the release is on the pendant.

## SRVO-005 Robot Overtravel

A joint axis moved beyond its software limit.

Recovery procedure:

1. With the robot in T1 mode, jog the offending axis back inside its limit.
   Use the alarm screen to identify which axis (J1..J6).
2. If the robot is power-down at limit, hold **RESET + Move** on the
   pendant during power up to release the brake long enough to jog away.
3. Inspect the gripper or fixturing that caused the overtravel; recheck
   reference positions.

## SRVO-007 External E-stop

A safety circuit in the cell is open. Check the safety mat, light curtain,
and door interlocks.
