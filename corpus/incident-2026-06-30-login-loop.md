---
id: incident-2026-06-30-login-loop
title: "Incident EB-2210: web login loops back to the login page"
type: incident
product: online-banking
date: 2026-06-30
---

## Summary

Between 2026-06-30 06:00 and 2026-07-01 14:30, customers whose browser blocked the session cookie (strict privacy settings or certain ad-blocker rules) were redirected back to the login page after a successful pushTAN approval, in an endless loop. Error code in the browser console and support tooling: **EB-2210**.

## Status

Resolved on 2026-07-01 with release 2026.26: the session token no longer depends on the third-party measurement cookie that privacy tools blocked.

## Handling residual cases

A customer still reporting EB-2210 after 2026-07-01 has cached redirects: clear the browser cache for aventra-bank.example or use a private window once. The mobile app was never affected — offering the app is the fastest unblock during any web login incident.