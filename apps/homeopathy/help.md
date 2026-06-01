# Homeopathy

Keep track of your homeopathic remedy collection — what you have, how full each
bottle is, where it's stored, and what needs reordering.

## Overview

Homeopathy is an inventory for remedies. You define a few reference pieces once
(suppliers, medicines, remedies = medicine + strength, bottle sizes, storage
locations), then track each physical **bottle** with its fullness and location.
From that, the app can tell you what you have, where it lives, and what's running
low and needs reordering — grouped by supplier.

## Screens

- **Inventory.** Your bottles, grouped by strength (highest potency first) then by
  medicine name; filter by location, strength, or "low only".
- **Bottle detail.** A bottle's remedy, size, location, fullness, and notes —
  update fullness as you use it.
- **Reorder list.** Everything at ¼ full or below, grouped by supplier, so you
  know what to buy.
- **Reference data.** Suppliers, medicines, remedies, bottle sizes, and locations.

## Example workflows

**Set up a remedy (first time)**
- Order matters: supplier → medicine → remedy (medicine + strength) → bottle.
- *Through chat:* "add Hahnemann Labs as a supplier", "add the remedy Arnica 30C",
  "add a 1-dram bottle of Arnica 30C in Drawer 6, half full".

**Check what you have / where it is**
- *In the app:* search or filter the inventory.
- *Through chat:* "do we have Arnica 30C?", "where's the Nux Vomica?",
  "show everything in Drawer 6".

**Update and reorder**
- *In the app:* set a bottle's fullness (Empty, ¼, ⅓, ½, ⅔, ¾, Full).
- *Through chat:* "the Arnica is about a quarter left", then "what do I need to
  order?" → the reorder list (≤ ¼ full), grouped by supplier.

## Tips

- Strength is free-form (6C, 30C, 200C, 1M, tincture/MT, …).
- Tools accept names, not IDs — just say the medicine/location.
- For conventional medications and medical history, use the **Medical** app instead.

## Your data

Your suppliers, medicines, remedies, bottles, fullness, and locations are **saved
in the database and pulled into Skipper's memory**, so you can ask "what's low?"
or "where's the Arnica?" any time. It stays within your household.
