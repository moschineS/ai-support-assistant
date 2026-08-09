---
id: incident-2026-07-02-pos-declines
title: "Incident CP-0031: card payments declined at point of sale"
type: incident
product: cards
date: 2026-07-02
---

## Summary

On 2026-07-02 between 12:10 and 16:45, roughly 8 percent of point-of-sale card payments were declined with reference **CP-0031** although accounts had sufficient funds and cards were not blocked. Online card payments and ATM withdrawals were unaffected.

## Status

Resolved 2026-07-02 16:45. Cause: a faulty rule deployment in the transaction authorization service double-counted pending reservations against the card limit. The rule was rolled back.

## Customer impact and handling

Declined payments were never booked — no money moved and no cleanup is needed on the account. Customers who saw CP-0031: apologize, confirm the card is fine, and reassure that no block exists and no action is required. Merchants may have created duplicate payment attempts; only the final successful one appears in transactions. Any customer claiming an actual double booking follows the normal dispute process.