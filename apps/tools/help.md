# Tools

A browser for the capabilities Skipper can use — the tool categories, the tools
in each, and the guide behind them.

## Overview

Everything Skipper can *do* (look up weather, manage reminders, control the smart
home, act on any app) is a "tool," organized into categories. Tools is a
read-only inspector of that registry: browse the categories, see which tools each
one exposes, and read the long-form guide that tells Skipper how to use them.
It's a power-user/developer view — day to day you just ask Skipper and it picks
the right tool itself.

## Screens

- **Categories.** The tool categories (core, web, weather, an entry per app, …).
- **Category detail.** The tools in a category and what each does, plus the guide
  markdown that documents them.

## Example workflows

**See what Skipper can do**
- *In the app:* browse categories and expand one to see its tools.
- *Through chat:* "what can you do?", "what tools do you have for weather?"

**Understand routing**
- *In the app:* the categories show how tools are grouped — useful when a request
  isn't picking up the tool you expected (a tool must be in a category to load).

## Tips

- This is a **read-only** developer/power-user view; you normally don't need it —
  just ask Skipper in chat.
- If chat ever says it "doesn't have a tool" for something an app clearly does,
  this view helps confirm the tool is registered in a category.

## Your data

Tools **owns no records of its own** — it displays the live tool registry. There's
nothing here to create or store, and nothing enters Skipper's memory from it.
