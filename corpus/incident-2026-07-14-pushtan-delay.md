---
id: incident-2026-07-14-pushtan-delay
title: "Incident EB-1042: delayed pushTAN approval prompts"
type: incident
product: online-banking
date: 2026-07-14
---

## Summary

Since 2026-07-14 approximately 08:40, a subset of customers receives pushTAN approval prompts with delays of 2 to 15 minutes. Logins and payments fail when the prompt expires (prompts are valid 5 minutes). Error code shown to affected customers: **EB-1042**.

## Status

Ongoing, mitigated. The push notification dispatcher was failed over to the secondary provider at 11:20; delays dropped sharply but are not yet fully cleared for Android devices with aggressive battery optimization.

## Workaround for support agents

Tell customers to open the pushTAN app manually and use "Pending approvals" — the prompt is always listed there immediately, independent of push delivery. Approving from inside the app works normally. Advise Android users to exclude the pushTAN app from battery optimization (Settings, then Apps, then Special access).

## Root cause (preliminary)

Elevated latency at the primary push delivery provider, aggravated by a retry storm from our dispatcher. Full root-cause analysis follows resolution.