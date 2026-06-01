# Automation

Control and check your smart home through Skipper — lights, switches, fans,
sensors, locks, media devices — via a Home Assistant connection.

## Overview

Automation bridges Skipper to **Home Assistant (HA)**. Once connected, you can
ask Skipper in plain language to turn things on/off, set lights, read a sensor,
or check a door — using friendly names ("the office lamp", "garage door") rather
than technical entity IDs. Skipper learns those friendly names (aliases) as you
use them. This app is mostly driven by **chat and voice**, not a lot of clicking.

## Setup

This app stays idle until Home Assistant is connected: add your **HA URL** and a
**long-lived access token** in **Settings → Automation** (see
`docs/03-extended-functionality.md`). Until then, the controls have nothing to talk to.

## Using it

- **Friendly names + aliases.** Say "office lamp" or "tv" — Skipper resolves it
  to the right HA device and remembers the mapping. You can correct a mapping by
  telling it the right device.
- **Control:** lights, switches, fans, media players, climate, etc.
- **Read:** sensors and binary sensors (temperature, humidity, motion, door/window
  open/closed, battery levels, connectivity).
- The app surfaces your saved device aliases and lets Skipper find low/dead batteries.

## Example workflows

**Turn something on/off**
- *Through chat/voice:* "turn off the living room lights", "toggle the office fan".

**Set a light**
- *Through chat:* "dim the kitchen lights to 30%", "make the bedroom light warm white".

**Check a sensor / door (right now)**
- *Through chat:* "is the garage door closed?", "how warm is the office?",
  "any low batteries?"

**Note on weather:** "what's the temperature *outside* right now" uses your HA
outdoor sensor; forecasts, rain chance, or "what's the weather" use the **Weather**
app instead (HA only knows the present moment at your sensors).

## Tips

- You don't need to know entity IDs — use everyday names; aliases are learned.
- For real device control Skipper calls HA services (not raw state edits), so
  actions actually take effect.

## Your data

Your **device aliases** (the friendly-name → HA-device mappings) are **saved and
pulled into Skipper's memory**, so naming gets better over time. Live sensor
readings and device states are read on demand from Home Assistant and are not
stored here; your HA URL/token live encrypted in Settings, never in chat.
