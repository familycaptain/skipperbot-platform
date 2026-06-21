# Raspberry Pi hardware + setup guide (incl. NVMe boot)

This guide is for people building a Skipper host **on a Raspberry Pi, starting
from bare hardware**. It covers what to buy, how to bring the Pi up, and — the
part most people get stuck on — how to **boot and run from an NVMe SSD** instead
of a microSD card.

> **Do you need this guide?** Only if you're assembling a Raspberry Pi from
> parts. If you already have a working Linux/macOS/Windows machine (or a Pi
> that already boots), skip straight to
> [**docs/01-base-platform-setup.md**](01-base-platform-setup.md) to install the
> software.

**Roughly $150–220 in parts and ~1–2 hours of hands-on time** (plus an unattended
OS-write/clone wait). That's in the same spirit as the ~5-minute / ~30-minute
estimates in [01](01-base-platform-setup.md) — this one is longer because you're
building the machine, not just installing software.

Everything below is **one concrete example, not the only option.** Brands are
named only to be specific; equivalent parts from any reputable vendor work just
as well. There are no affiliate links.

---

## At-a-glance shopping list

| Part | Required? | Example | Why |
|------|-----------|---------|-----|
| Raspberry Pi 5, **8 GB** (16 GB better) | **Required** | Pi 5 8GB | Postgres + pgvector + the agent + the web build want headroom; 8 GB is the floor, more RAM = more comfortable. |
| NVMe SSD, 256–512 GB | **Required** | M.2 2280 NVMe, 256 GB+ | The database, embeddings, uploads, and backups live here. Far faster and far more durable than a microSD card. |
| M.2 HAT+ (PCIe) for Pi 5 | **Required** | Official Raspberry Pi M.2 HAT+ | Physically connects the NVMe SSD to the Pi 5's PCIe lane. Get one sized for your SSD's length (2230/2242/2280). |
| USB-C PD power supply, **27 W** | **Required** | Official 27 W USB-C PSU | The Pi 5 + an NVMe drive draws real current; an underpowered PSU causes brown-outs and SSD drop-outs. Use a 27 W (5 V/5 A) supply. |
| Active cooling | **Required** | Official Active Cooler, or a case with a fan | The Pi 5 throttles under sustained load (which a 24/7 agent + DB is). A fan/heatsink keeps it stable. |
| Case | Recommended | Any Pi 5 case that fits the HAT+ | Protects the board and routes airflow. Must have clearance for the M.2 HAT+. |
| microSD card, 16–32 GB | **Required (temporary)** | Any A1/A2 card | Used to do the **first** boot and then migrate onto the NVMe (see below). You can repurpose it afterward. |
| Ethernet cable | Recommended | Cat5e/Cat6 | Wired is more reliable than Wi-Fi for an always-on host. Wi-Fi works too. |
| UPS / battery backup | Optional | Any small UPS | Protects the database from sudden power loss / corruption. Nice for a 24/7 host. |

If you already own a recent Pi 5, an NVMe + HAT+, and a 27 W PSU, you're set —
skip the shopping and go to **Bring-up** below.

---

## Why these parts (the longer version)

- **Pi 5, 8 GB minimum.** Skipper runs Postgres (with pgvector), the Python
  agent, and builds the web UI. 8 GB is the practical floor; 16 GB gives more
  breathing room if you add apps. A Pi 4 *can* run it but the Pi 5's PCIe lane is
  what makes real NVMe boot easy — this guide assumes a Pi 5.
- **NVMe SSD over microSD.** microSD cards are slow and wear out — a database
  doing frequent small writes will eventually corrupt a cheap card. An NVMe SSD
  is dramatically faster and rated for far more writes. This is the single
  biggest reliability upgrade for a self-hosted Skipper.
- **M.2 HAT+.** The Pi 5 exposes a single PCIe lane via an FFC connector; the
  HAT+ adapts it to an M.2 slot. Match the HAT+ to your SSD's physical length.
- **27 W PSU.** Power is the most common cause of mystery NVMe/SSD failures on a
  Pi. Use the official 27 W (or an equivalent 5 V/5 A PD) supply; don't run a Pi
  5 + NVMe off a phone charger.
- **Active cooling.** A continuously-running agent + database keeps the CPU busy;
  without a fan the Pi 5 thermally throttles and gets slow/unstable.

---

## Bring-up

### 1. Flash the microSD first

Even though you'll end up booting from NVMe, the simplest path is to start from a
microSD card and migrate.

1. Install **Raspberry Pi Imager** on your laptop (<https://www.raspberrypi.com/software/>).
2. Flash the **current 64-bit Raspberry Pi OS** to the microSD. (Use whatever the
   current release is — this guide deliberately does not pin a codename.) The
   64-bit (arm64) build is required for Skipper's dependencies.
3. In Imager's settings, set a **hostname** (this guide uses
   `your-skipper-host.local` as a placeholder — pick your own), enable **SSH with
   a public key**, and create a **non-default user** (don't keep the stock `pi`
   account as your main login — see Hardening).
4. Insert the card, attach the NVMe SSD to the M.2 HAT+, connect Ethernet (or
   configure Wi-Fi in Imager), and power on with the 27 W PSU.
5. SSH in and update everything:
   ```bash
   sudo apt update && sudo apt full-upgrade -y
   sudo reboot
   ```

### 2. Make the Pi boot from NVMe

The goal: the OS lives and boots on the NVMe SSD; the microSD becomes optional.

1. **Confirm the NVMe is detected.** After boot, the drive should appear:
   ```bash
   lsblk
   ```
   You should see an `nvme0n1` device. If you don't, stop and see
   *If it won't boot from NVMe* below — it's almost always HAT+ seating or PCIe
   not being enabled.

2. **Enable PCIe / NVMe** if needed. On recent releases the firmware config lives
   at **`/boot/firmware/config.txt`** (older releases use `/boot/config.txt`).
   Ensure PCIe is enabled:
   ```
   # /boot/firmware/config.txt
   dtparam=pciex1
   ```
   **PCIe Gen 3 is an optional speed-up and is officially *uncertified* on the
   Pi 5.** You can try it by adding `dtparam=pciex1_gen=3`, but if the NVMe drops
   out or won't enumerate, **remove that line and fall back to the default
   (Gen 2)**, which is rock-solid.

3. **Update the bootloader and set NVMe boot order.** Use `raspi-config`
   (Advanced Options → Bootloader / Boot Order) or `rpi-eeprom-config` to update
   the bootloader EEPROM and set the boot order to prefer NVMe. (Menu wording
   shifts between OS versions, so this guide refers to the *intent* — "update the
   bootloader, prefer NVMe in the boot order" — rather than exact menu numbers.)
   ```bash
   sudo raspi-config        # Advanced Options -> Bootloader Version (latest), Boot Order (NVMe first)
   # or, to edit the EEPROM config directly:
   sudo rpi-eeprom-config --edit   # set BOOT_ORDER so NVMe is tried before SD
   ```

4. **Copy the OS onto the NVMe.** The easiest tool is **Raspberry Pi Imager run
   *on the Pi itself*** (Accessories → Raspberry Pi Imager) or the **SD Card Copier**
   utility: clone the running microSD system onto `nvme0n1`. (Alternatively,
   re-flash Raspberry Pi OS directly to the NVMe from your laptop using a USB↔M.2
   enclosure.)

5. **Boot from NVMe and expand the filesystem.** Power off, **remove the
   microSD**, and power back on — the Pi should now boot from the NVMe. Expand the
   root filesystem to fill the SSD:
   ```bash
   sudo raspi-config        # Advanced Options -> Expand Filesystem
   sudo reboot
   ```

### 3. Verify root is actually on the NVMe

Don't assume — prove it. After booting with the microSD removed:

```bash
findmnt /            # SOURCE should be /dev/nvme0n1p2 (an nvme... device), not mmcblk...
lsblk                # root partition sits under nvme0n1
df -h /              # the root filesystem is the NVMe's size, not the SD card's
```

If `findmnt /` shows an `nvme0n1...` source, you're booting and running from the
NVMe. 🎉

### If it won't boot from NVMe

- **`nvme0n1` missing from `lsblk`:** re-seat the SSD in the M.2 HAT+ (and the
  HAT+ on the Pi's PCIe FFC connector — check the ribbon is fully inserted and
  the latch closed). Confirm PCIe is enabled in `config.txt`. If you set PCIe
  **Gen 3**, remove that line and retry at the default Gen 2.
- **Boots from microSD even with NVMe present (or won't boot with SD removed):**
  the boot order / bootloader EEPROM wasn't updated. Re-insert the microSD, run
  the bootloader update again (`raspi-config` → Bootloader, latest) and set the
  boot order to prefer NVMe, then retry with the SD removed.
- **Random drop-outs / reboots under load:** almost always power. Use the 27 W
  official PSU (or a true 5 V/5 A PD supply), not a phone charger or a hub port.

---

## Basic hardening

A self-hosted box should be at least minimally locked down. These steps are all
**net-positive** — they make the machine safer, never weaker.

- **SSH key authentication.** You set a public key during imaging; keep using
  keys. **Do not** switch SSH back to password authentication.
- **Use a non-default user, lock the stock `pi` account.** Log in as the user you
  created, give it a strong password (or key-only), and **lock or remove the
  default `pi` account** so the well-known default login can't be used:
  ```bash
  sudo passwd -l pi        # lock the default account (or: sudo deluser --remove-home pi)
  ```
- **Keep it patched.** Apply updates regularly:
  ```bash
  sudo apt update && sudo apt full-upgrade -y
  ```
- **Leave the firewall on.** If you enable a firewall (e.g. `ufw`), only open the
  ports you actually use (SSH, and the Skipper web port if you reach it across
  your LAN). Don't disable the firewall or expose ports you don't need, and never
  paste real secrets into files on a shared/public machine.

---

## Next: install Skipper

Your Pi is now a clean, NVMe-booting 64-bit Linux host — exactly the "clean
machine" that the software guide starts from. Continue with:

➡️ [**docs/01-base-platform-setup.md**](01-base-platform-setup.md)

A few Pi-specific notes for that guide:

- **Use the Docker path.** It bundles Postgres 18 + pgvector + Python 3.12 +
  Node 24, which is by far the least fiddly option on a Pi. Docker runs natively
  on 64-bit Raspberry Pi OS (the 01 guide's Docker install steps explicitly cover
  Raspberry Pi OS).
- **arm64 everywhere.** Because you flashed the 64-bit OS, the container images
  and dependencies resolve correctly. (A 32-bit OS will not work.)
- **Memory.** On an 8 GB Pi the web build and the database coexist fine; if you
  later add many apps and feel pressure, that's the signal to move to a 16 GB Pi.

That's it — bare hardware to a running Skipper.
