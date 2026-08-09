---
id: incident-2026-05-02-push-notifications
title: "Incident NT-2205: push notification outage"
type: incident
product: mobile-app
date: 2026-05-02
---

## Summary

From 2026-05-02 21:00 to 2026-05-03 02:30, no push notifications were delivered (incoming payments, card transactions, low balance, security alerts). Support reference: **NT-2205**. This also delayed pushTAN prompts; "Pending approvals" inside the pushTAN app kept working throughout.

## Status

Resolved. A certificate on the notification gateway expired; monitoring now alerts 21 days before certificate expiry and the renewal is automated.

## Customer questions afterwards

Notifications from the outage window were dropped, not queued — they will never arrive late. All underlying events are visible in the app (transactions, mailbox); nothing was lost except the notification itself. Customers uneasy about missed security alerts can be shown the login history under Profile, then Security, then Devices and sessions.