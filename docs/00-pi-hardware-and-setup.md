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

**Roughly ~1–2 hours of hands-on time** (plus an unattended
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
| Raspberry Pi 5, **16 GB (required)** | **Required** | Pi 5 16GB | Postgres + pgvector + the agent + the web build want headroom. 8 GB will generally not have enough memory to run Skipper; **16 GB is required** for comfortable 24/7 operation (with the swap setup below). |
| NVMe SSD, 256–512 GB | **Required** | **M.2 2242** NVMe (22×42 mm), 256 GB+ | The database, embeddings, uploads, and backups live here. Far faster and more durable than a microSD card. **Buy the short 2242 length** — see the warning below the table. |
| M.2 HAT+ (PCIe) for Pi 5 | **Required** | Official Raspberry Pi M.2 HAT+ | Physically connects the NVMe SSD to the Pi 5's PCIe lane. The official HAT+ takes a **2230 or 2242** drive — match your SSD to it. |
| USB-C PD power supply, **27 W** | **Required** | Official 27 W USB-C PSU | The Pi 5 + an NVMe drive draws real current; an underpowered PSU causes brown-outs and SSD drop-outs. Use a 27 W (5 V/5 A) supply. |
| Active cooling | **Required** | Official Active Cooler, or a case with a fan | The Pi 5 throttles under sustained load (which a 24/7 agent + DB is). A fan/heatsink keeps it stable. |
| Case | Recommended | Any Pi 5 case that fits the HAT+ | Protects the board and routes airflow. Must have clearance for the M.2 HAT+. |
| microSD card, 16–32 GB | **Required (temporary)** | Any A1/A2 card | Used to do the **first** boot and then migrate onto the NVMe (see below). You can repurpose it afterward. |
| Ethernet cable | Recommended | Cat5e/Cat6 | Wired is more reliable than Wi-Fi for an always-on host. Wi-Fi works too. |
| UPS / battery backup | Optional | Any small UPS | Protects the database from sudden power loss / corruption. Nice for a 24/7 host. |

> ⚠️ **Buy a 2242 (22×42 mm) NVMe SSD — not the common 2280.** The official
> Raspberry Pi 5 M.2 HAT+ only fits short **2230/2242** drives. The 2280 length
> that most NVMe listings default to **will not physically seat** on the HAT+, so
> a 2242 is the safe choice. Double-check the length before you buy.

If you already own a recent Pi 5, an NVMe + HAT+, and a 27 W PSU, you're set —
skip the shopping and go to **Bring-up** below.

---

## Why these parts (the longer version)

- **Pi 5, 16 GB required.** Skipper runs Postgres (with pgvector), the Python
  agent, and builds the web UI. 8 GB will generally not have enough memory to run
  Skipper; **16 GB is required** for 24/7 operation (and the swap setup below
  assumes a 16 GB board).
  A Pi 4 cannot run Skipper — you need a Pi 5 (16 GB), whose PCIe lane also makes
  real NVMe boot easy. This guide assumes a Pi 5, 16 GB.
- **NVMe SSD over microSD.** microSD cards are slow and wear out — a database
  doing frequent small writes will eventually corrupt a cheap card. An NVMe SSD
  is dramatically faster and rated for far more writes. This is the single
  biggest reliability upgrade for a self-hosted Skipper.
- **M.2 HAT+.** The Pi 5 exposes a single PCIe lane via an FFC connector; the
  HAT+ adapts it to an M.2 slot. The official Pi 5 M.2 HAT+ fits short
  **2230/2242** drives only — get a **2242** SSD (not the common 2280). For the
  full deep-dive on Pi 5 NVMe + HAT+ specifics (compatible drives, speeds, edge
  cases), see **Jeff Geerling's Pi 5 NVMe writeups** (<https://www.jeffgeerling.com/>).
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
   sudo rpi-eeprom-update -a        # update the bootloader EEPROM to the latest
   sudo raspi-config                # Advanced Options -> Bootloader Version (latest), Boot Order (NVMe first)
   # or, to edit the EEPROM config directly:
   sudo rpi-eeprom-config --edit    # set BOOT_ORDER=0xf416  (NVMe first, then SD, then USB — keeps SD as a fallback)
   ```
   `BOOT_ORDER=0xf416` is read right-to-left (`6`=NVMe, `1`=SD, `4`=USB): NVMe is
   tried first and the SD card stays a fallback, so a bad NVMe can't lock you out.

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

### 4. Configure swap (2 GB zram + 6 GB on-disk)

**Target state: 16 GB RAM + 2 GB zram + 6 GB on-disk swap, booting off the NVMe.**
Two swap layers, each with a distinct job:

- **zram** is compressed swap held *in RAM* — very fast, and it spares the SSD
  from swap write-wear. It absorbs ordinary memory pressure.
- **On-disk swap** is the overflow safety net. It lives on the NVMe and survives
  both an out-of-memory spike *and* a reboot, so a memory burst (a big web build,
  many apps at once) degrades gracefully instead of OOM-killing the agent or
  Postgres.

#### (a) 2 GB zram

Install `zram-tools` and configure a **fixed 2 GB** device. **Gotcha:** in
`/etc/default/zramswap`, `PERCENT` (default 50) *overrides* `SIZE` — so you must
disable `PERCENT`, otherwise `SIZE` is ignored and you'd get ~50 % of RAM (~8 GB
on a 16 GB Pi) instead of 2 GB.

```bash
sudo apt install -y zram-tools
# Disable PERCENT (it overrides SIZE), then set a fixed 2 GB (2048 MB) zstd device:
sudo sed -i 's/^PERCENT/#PERCENT/; s/^#\?ALGO=.*/ALGO=zstd/; s/^#\?SIZE=.*/SIZE=2048/' /etc/default/zramswap
grep -q '^ALGO=' /etc/default/zramswap || echo 'ALGO=zstd' | sudo tee -a /etc/default/zramswap
grep -q '^SIZE=' /etc/default/zramswap || echo 'SIZE=2048' | sudo tee -a /etc/default/zramswap
sudo systemctl enable --now zramswap.service
```

Verify — you should see a `/dev/zram0` device of ~2 GB:

```bash
swapon --show     # expect /dev/zram0, SIZE ~2G, high priority
zramctl           # zram0, algorithm zstd, DISKSIZE ~2G
```

#### (b) 6 GB on-disk swap (persistent)

Use a **manual swapfile on the NVMe** — this works on any Raspberry Pi OS image
and is the most reliable path (the `dphys-swapfile` service is not always
installed). Create a 6 GB file, lock down its permissions, and make it persist
across reboots via `/etc/fstab`:

```bash
sudo fallocate -l 6G /swapfile        # (or: sudo dd if=/dev/zero of=/swapfile bs=1M count=6144)
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
# Persist across reboots:
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Verify it's active and survives a reboot:

```bash
swapon --show     # expect /swapfile, TYPE file, SIZE 6G
sudo reboot
# after reboot, confirm it came back:
swapon --show     # /swapfile should still be listed (alongside /dev/zram0)
```

**Alternative — `dphys-swapfile`** (only if it's already installed; current Pi OS
Lite often does **not** ship it). It caps swap at 2 GB by default
(`CONF_MAXSWAP=2048`), so raise both limits, then regenerate:

```bash
sudo apt install -y dphys-swapfile    # if not already present
sudo sed -i 's/^#\?CONF_SWAPSIZE=.*/CONF_SWAPSIZE=6144/; s/^#\?CONF_MAXSWAP=.*/CONF_MAXSWAP=6144/' /etc/dphys-swapfile
sudo dphys-swapfile swapoff && sudo dphys-swapfile setup && sudo dphys-swapfile swapon
swapon --show     # expect the dphys swap file (e.g. /var/swap) at 6G
```

> **Pick ONE on-disk method** — a manual `/swapfile` **or** `dphys-swapfile`, not
> both (two on-disk swaps would compete). zram from step (a) runs alongside
> whichever on-disk method you choose.

When done, `swapon --show` lists a `/dev/zram0` (~2 G) **and** a 6 G on-disk swap —
the target state above.

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
- **Memory.** This guide targets a **16 GB Pi 5 with 2 GB zram + 6 GB on-disk
  swap** (see *Configure swap* above) — comfortable headroom for the web build,
  Postgres, and many apps. An 8 GB board will generally not have enough memory to
  run Skipper — 16 GB + swap is the required baseline for a 24/7 host.

That's it — bare hardware to a running Skipper.
