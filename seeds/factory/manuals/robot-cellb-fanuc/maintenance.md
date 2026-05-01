---
title: Fanuc R-30iB Preventive Maintenance
asset_id: robot-cellb-fanuc
brand: Fanuc
model: R-30iB Plus
section: preventive-maintenance
---

# Fanuc R-30iB Preventive Maintenance

## Daily

- Visually inspect the cable harnesses for chafe at all axis covers.
- Verify no alarm history newer than the last shift.
- Check that the gripper supply pressure reads 5.5 bar at the J6 manifold.

## 500 Hour

- Lubricate the J1 reducer with `Vigogrease RE0` (Fanuc spec).
- Inspect timing belts at J5 and J6 for cracks. Replace as a pair if either is suspect.

## Annual

- Back up the controller via FTP. Compare to the production-approved
  configuration.
- Replace the controller battery (`A98L-0031-0028`) when the BAT alarm flag is set.
