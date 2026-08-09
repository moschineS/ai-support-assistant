---
id: incident-2026-05-21-statements-missing
title: "Incident ST-7001: April statements missing from the mailbox"
type: incident
product: accounts
date: 2026-05-21
---

## Summary

The monthly PDF statements for April 2026 were not delivered to the electronic document mailbox for customers whose surname begins with S through Z. Support tooling reference: **ST-7001**. Balances and transaction history were always correct — only the rendered PDF was missing.

## Status

Resolved 2026-05-23. The statement rendering batch aborted midway due to a storage quota and was re-run after the quota raise. All missing statements were delivered by 2026-05-23 22:00 and carry their original statement date.

## Handling late claims

A customer still missing a April 2026 statement after 2026-05-23: verify the document mailbox filter is not set to "last 30 days" — re-delivered statements sort under their original April date, which the default filter hides. The filter, not a missing document, explains nearly all residual reports.