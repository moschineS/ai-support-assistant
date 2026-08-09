---
id: incident-2026-03-19-depot-orders
title: "Incident DP-3302: delayed depot order confirmations"
type: incident
product: investments
date: 2026-03-19
---

## Summary

On 2026-03-19, a high-volume trading day, push notifications and mailbox settlement notes for executed depot orders arrived up to 4 hours late. Support reference: **DP-3302**. Order execution itself was never delayed — only the confirmations were.

## Status

Resolved 2026-03-20. The notification queue for securities events was resized and confirmations now process independently of market data load.

## Key message for customers

The order status page (Depot, then Orders) is the authoritative, real-time source: an order shown as "executed" there is executed at the shown price, regardless of whether the push notification or settlement note has arrived yet. Customers must not re-submit an order because a confirmation is late — this caused double executions for a handful of customers on 2026-03-19, which the bank unwound at its own cost. Any similar case goes to the trading desk escalation immediately.