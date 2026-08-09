---
id: incident-2026-07-28-android-crash
title: "Incident MB-1103: Aventra Mobile crashes on Android 15 beta"
type: incident
product: mobile-app
date: 2026-07-28
---

## Summary

Aventra Mobile 7.4.x crashes on startup on devices running the Android 15 beta program (QPR beta builds). Crash reference in the app's error dialog: **MB-1103**. Stable Android 15 and all other versions are unaffected. Roughly 0.4 percent of Android users are on beta builds.

## Status

Ongoing. Fix scheduled with app release 7.5 (expected mid-August 2026); the beta OS changed the WebView sandbox initialization the app relies on at startup.

## Workaround for support agents

There is no in-app workaround. Options for affected customers, in order of preference: leave the OS beta program (Google settings, then System, then Beta program) and reinstall the stable OS build; use web banking in the phone browser, which is fully functional; or use a second bound device if one exists. The pushTAN app is a separate binary and is NOT affected — approvals keep working, so web banking on the same phone remains a complete workaround.