---
title: Cognex IS-2000 QC Station Safety
asset_id: vision-qc-cognex
brand: Cognex
model: In-Sight 2000
section: safety
---

# Cognex IS-2000 QC Station Safety

## Hazards

The QC station itself is low-energy (24 VDC, PoE). The hazards in this
work area come from the upstream conveyor and the marker-printer head:

- Pinch points where boxes enter the QC bay.
- Hot ink at the upstream printer head.

## LOTO

When servicing the QC sensor itself, isolating the PoE injector at the
network cabinet **NW-LINE3** is sufficient. The conveyor must be locked
out separately at `vfd-line3-conveyor` if any maintenance requires
reaching across the belt.

## PPE

Safety glasses, ear protection (line floor noise), and standard cut-resistant
gloves when handling product.
