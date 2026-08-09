---
id: incident-2026-06-05-instant-reject
title: "Incident TR-4400: instant transfers rejected for one partner bank group"
type: incident
product: payments
date: 2026-06-05
---

## Summary

Since 2026-06-05 07:30, SEPA instant transfers to banks of one partner group (BICs beginning GENO) are rejected with error code **TR-4400** and reason "recipient unreachable". Standard transfers to the same accounts work normally. The cause is on the recipient group's side (their instant payments gateway maintenance overran).

## Status

Resolved 2026-06-05 19:10 when the recipient group's gateway returned. Rejections between 07:30 and 19:10 were final; no money left any account (reservations cleared automatically within minutes).

## Handling

Customers with an urgent payment during such a window have two options: execute as a standard transfer (arrives next business day) or retry the instant transfer later. A TR-4400 rejection never means the recipient account is wrong or closed — do not tell customers to doubt the IBAN over this code; the reason text distinguishes unreachable from account-not-found.