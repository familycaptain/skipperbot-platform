# Timers

Short countdown timers for the kitchen, workouts, pomodoros — anything you'd
use an egg timer for. When a timer finishes, Skipper sends you a notification.

## Overview

A timer is a quick **countdown** (seconds to a few minutes). It's different from
a **reminder**: a reminder fires at a wall-clock time ("at 3pm", "tomorrow
morning"); a timer counts down a duration from right now. For anything more than
~30 minutes out, use a reminder instead — timers live in memory and don't
survive a restart.

## How to use it

Just ask Skipper, in chat or by voice:

- **Start one** — "set a 5 minute timer", "30 second timer", "timer for 90
  seconds for the eggs", "10 minute pomodoro". Skipper starts it immediately.
- **Name it** (optional) — "5 minute timer for the pasta" labels it *pasta*, so
  the finish notification and the list show what it's for.
- **See what's running** — "what timers do I have?", "list my timers".
- **Cancel one** — "cancel the pasta timer", or "cancel that timer" right after
  setting one.

## When it fires

You get a notification — **⏱️ Timer done: \<name\> (\<duration\>)** — delivered
the usual way (web, mobile push, Discord). It's one-shot: it fires once and
that's it, no snooze loop.

## Good to know

- Timers are **per person** — the one who asked gets the notification.
- They're **in-memory**: if the server restarts, running timers are cleared.
  Use a reminder for anything you can't afford to lose.
- There's no separate Timers screen — timers are entirely chat/voice driven.
