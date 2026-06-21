"""Chores App MCP Tools — kids' recurring household chore rotation.

For one-off paid tasks see the Bounties app — these tools are for the
*recurring weekly* chore rotation only.

Every tool that mutates data accepts `acted_by` (the caller's username).
Parents can act on anyone; kids can only check off
their own chores. Kid/zone/chore CRUD is parent-only.
"""

import datetime as dt
import logging

logger = logging.getLogger(__name__)


# ===========================================================================
# Internal helpers — kid resolution + permissions
# ===========================================================================

def _resolve_kid(identifier: str) -> dict | None:
    """Look up a kid by kid_id, user_id, or display name (case-insensitive)."""
    from apps.chores import data as _dl

    if not identifier:
        return None
    ident = identifier.strip()
    if not ident:
        return None

    # 1. kid_id (kid-XXXXXXXX)
    if ident.startswith("kid-"):
        kid = _dl.get_kid(ident)
        if kid:
            return kid

    # 2. user_id (e.g., a kid's username) — exact match
    kid = _dl.get_kid_by_user(ident.lower())
    if kid:
        return kid

    # 3. display name (case-insensitive)
    for k in _dl.list_kids(active_only=False):
        if k["name"].lower() == ident.lower():
            return k

    return None


def _is_parent(username: str) -> bool:
    from data_layer import users as _users
    actor = _users.get_user(username)
    if not actor:
        return False
    return _users.has_any_role(actor, "parent", "admin")


def _dow_name(dow: int) -> str:
    return ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][dow]


def _parse_dow(value) -> int:
    """Accept either an int 0..6 or a weekday name (case-insensitive)."""
    if isinstance(value, int):
        return value % 7
    s = str(value).strip().lower()
    if s.isdigit():
        return int(s) % 7
    mapping = {
        "sun": 0, "sunday": 0,
        "mon": 1, "monday": 1,
        "tue": 2, "tues": 2, "tuesday": 2,
        "wed": 3, "weds": 3, "wednesday": 3,
        "thu": 4, "thur": 4, "thurs": 4, "thursday": 4,
        "fri": 5, "friday": 5,
        "sat": 6, "saturday": 6,
    }
    if s in mapping:
        return mapping[s]
    raise ValueError(f"Unknown day-of-week: {value!r}")


def _resolve_date(value: str = "") -> dt.date:
    from apps.chores import store as _store
    if not value:
        return _store.today_local()
    v = value.strip().lower()
    if v in ("today", ""):
        return _store.today_local()
    if v == "yesterday":
        return _store.today_local() - dt.timedelta(days=1)
    if v == "tomorrow":
        return _store.today_local() + dt.timedelta(days=1)
    return dt.date.fromisoformat(value)


# ===========================================================================
# Read tools
# ===========================================================================

def get_chores_today(kid: str = "", date: str = "") -> str:
    """List today's chore assignments.

    Args:
        kid: Optional kid (kid-id, a username, or display name). Empty = all kids.
        date: Optional date YYYY-MM-DD, or "today" / "yesterday" / "tomorrow". Default: today.

    Returns:
        Formatted summary of who has which chores today.

    Ack: Checking today's chores...
    """
    from apps.chores import store as _store

    target_date = _resolve_date(date)
    view = _store.today_by_kid(target_date)
    kid_filter = _resolve_kid(kid) if kid else None

    lines = [f"**Chores for {target_date.strftime('%a %b %#d, %Y') if hasattr(target_date, 'strftime') else target_date}**"]
    any_chores = False
    for k in view["kids"]:
        if kid_filter and k["id"] != kid_filter["id"]:
            continue
        assignments = k["assignments"]
        if not assignments:
            lines.append(f"\n_{k['name']}: nothing today._")
            continue
        any_chores = True
        lines.append(f"\n**{k['name']}**")
        for a in assignments:
            mark = "✓" if a["completed"] else "☐"
            note = f" — {a['note']}" if a["note"] else ""
            lines.append(f"  {mark} {a['chore_name']}  _({a['zone_name']})_{note}")
    if not any_chores and kid_filter:
        lines.append(f"\n_{kid_filter['name']} has no chores._")
    return "\n".join(lines)


def get_chores_week(kid: str = "", start_date: str = "") -> str:
    """Return a kid's 7-day chore strip (or every kid's, if no kid given).

    Args:
        kid: Optional kid (kid-id, username, or display name).
        start_date: Optional YYYY-MM-DD start (default: this Sunday).

    Returns:
        Day-by-day list of chores per kid.

    Ack: Building this week's chore schedule...
    """
    from apps.chores import store as _store

    start = _resolve_date(start_date) if start_date else None
    week = _store.week_by_kid(start)
    kid_filter = _resolve_kid(kid) if kid else None

    out = [f"**Week of {week['start_date']}**"]
    for day in week["days"]:
        day_date = day["date"]
        weekday = dt.date.fromisoformat(day_date).strftime("%a %b %#d") if hasattr(dt.date.fromisoformat(day_date), "strftime") else day_date
        out.append(f"\n__{weekday}__")
        for k in day["kids"]:
            if kid_filter and k["id"] != kid_filter["id"]:
                continue
            if not k["assignments"]:
                continue
            chores = ", ".join(
                f"{'✓' if a['completed'] else '☐'} {a['chore_name']}"
                for a in k["assignments"]
            )
            out.append(f"  {k['name']}: {chores}")
    return "\n".join(out)


def get_chore_history(kid: str = "", date_from: str = "", date_to: str = "",
                      limit: int = 30) -> str:
    """Show completion history for a kid (or everyone) in a date range.

    Args:
        kid: Optional kid (kid-id, username, or display name).
        date_from: YYYY-MM-DD, default: 30 days ago.
        date_to: YYYY-MM-DD, default: today.
        limit: Max rows. Default 30.

    Returns:
        Completion history.

    Ack: Looking up chore history...
    """
    from apps.chores import data as _dl
    from apps.chores import store as _store

    today = _store.today_local()
    df = _resolve_date(date_from) if date_from else today - dt.timedelta(days=30)
    dto = _resolve_date(date_to) if date_to else today
    kid_obj = _resolve_kid(kid) if kid else None

    rows = _dl.list_completions_in_range(
        date_from=df.isoformat(), date_to=dto.isoformat(),
        kid_id=kid_obj["id"] if kid_obj else None, limit=limit,
    )
    if not rows:
        return "No completions in that range."

    # Build a name map for chores
    chore_map = {c["id"]: c for c in _dl.list_chores(active_only=False)}
    kid_map = {k["id"]: k for k in _dl.list_kids(active_only=False)}

    lines = [f"**{len(rows)} completion(s) {df} → {dto}:**"]
    for r in rows:
        chore = chore_map.get(r["chore_id"], {})
        kid_rec = kid_map.get(r["kid_id"], {})
        when = (r["completed_at"] or "")[:16].replace("T", " ")
        lines.append(
            f"  • {r['chore_date']} — {kid_rec.get('name', '?')}: "
            f"{chore.get('name', r['chore_id'])} ({r['status']}) at {when}"
        )
    return "\n".join(lines)


def list_kids() -> str:
    """List all active kids in the Chores rotation.

    Ack: Listing kids...
    """
    from apps.chores import data as _dl
    kids = _dl.list_kids(active_only=True)
    if not kids:
        return "No kids configured."
    lines = [f"**{len(kids)} kid(s):**"]
    for k in kids:
        link = f" → user '{k['user_id']}'" if k["user_id"] else ""
        notify = f"  notify_morning={k['notify_morning']}"
        lines.append(f"  • {k['name']}  [{k['id']}]{link}  color={k['color']}{notify}")
    return "\n".join(lines)


def list_chore_zones() -> str:
    """List all zones with their members and chore counts.

    Ack: Listing chore zones...
    """
    from apps.chores import data as _dl
    zones = _dl.list_zones()
    if not zones:
        return "No zones configured."
    lines = [f"**{len(zones)} zone(s):**"]
    for z in zones:
        members = _dl.get_zone_members(z["id"])
        member_names = ", ".join(m["kid_name"] for m in members) or "(none)"
        chores = _dl.list_chores(z["id"])
        lines.append(
            f"  • {z['name']}  [{z['id']}]  rotation_start={z['rotation_start']}\n"
            f"      members: {member_names}\n"
            f"      chores: {len(chores)}"
        )
    return "\n".join(lines)


def get_chore_zone(zone: str) -> str:
    """Show full detail for a zone — members and the dow × position chore grid.

    Args:
        zone: Zone id (cz-XXXXXXXX) or zone name (case-insensitive).

    Ack: Loading zone detail...
    """
    from apps.chores import data as _dl
    z = _dl.get_zone(zone) if zone.startswith("cz-") else _dl.get_zone_by_name(zone)
    if not z:
        # case-insensitive name fallback
        for zz in _dl.list_zones():
            if zz["name"].lower() == zone.lower():
                z = zz
                break
    if not z:
        return f"Zone not found: {zone!r}"

    members = _dl.get_zone_members(z["id"])
    chores = _dl.list_chores(z["id"], active_only=False)

    lines = [
        f"**{z['name']}**  [{z['id']}]",
        f"rotation_start: {z['rotation_start']}",
        f"members ({len(members)}): " + ", ".join(f"{m['kid_name']}@{m['position']}" for m in members),
    ]
    if not chores:
        lines.append("\n_No chores defined._")
        return "\n".join(lines)

    # Group by dow
    by_dow: dict[int, list] = {}
    for c in chores:
        by_dow.setdefault(c["dow"], []).append(c)
    lines.append("")
    for d in sorted(by_dow.keys()):
        lines.append(f"  {_dow_name(d)}:")
        for c in sorted(by_dow[d], key=lambda x: x["position"]):
            tag = "" if c["active"] else "  (inactive)"
            note = f" — {c['note']}" if c["note"] else ""
            lines.append(f"    [{c['position']}] {c['name']}{note}  [{c['id']}]{tag}")
    return "\n".join(lines)


# ===========================================================================
# Check-off tools (kids + parents)
# ===========================================================================

def complete_chore(kid: str, chore: str, acted_by: str, date: str = "",
                   note: str = "") -> str:
    """Mark a chore done for a kid on a specific date.

    Args:
        kid: Kid identifier (kid-id, username, or display name).
        chore: Either a chore id (ch-XXXXXXXX) or a fuzzy chore name (e.g. "vacuum").
            When passing a name, the tool matches it against the kid's assigned
            chores for the date — only an assigned chore can be completed.
        acted_by: Username of the caller (so we know who checked it off).
        date: YYYY-MM-DD, or "today"/"yesterday". Default: today.
        note: Optional note.

    Returns:
        Confirmation.

    Ack: Checking off chore...
    """
    from apps.chores import store as _store

    kid_obj = _resolve_kid(kid)
    if not kid_obj:
        return f"Kid not found: {kid!r}"

    # Permission: parent can act on anyone; kid only on themselves
    if not _is_parent(acted_by):
        if kid_obj.get("user_id") != acted_by:
            return f"Only {kid_obj['name']} (or a parent) can check off their chores."

    target_date = _resolve_date(date)

    # Resolve chore — either ch-id, or fuzzy assignment lookup
    if chore.startswith("ch-"):
        chore_id = chore
        # Sanity-check the chore is actually assigned to this kid today
        view = _store.today_by_kid(target_date)
        for k in view["kids"]:
            if k["id"] != kid_obj["id"]:
                continue
            matching = [a for a in k["assignments"] if a["chore_id"] == chore_id]
            if not matching:
                return (
                    f"{kid_obj['name']} isn't assigned chore {chore_id} on "
                    f"{target_date.isoformat()}."
                )
            break
    else:
        match = _store.find_assignment_for_kid_by_name(
            kid_obj["id"], chore, target_date,
        )
        if not match:
            return (
                f"Couldn't find a chore matching {chore!r} for {kid_obj['name']} on "
                f"{target_date.isoformat()}. Try `get_chores_today` to see assignments."
            )
        chore_id = match["chore_id"]

    completion = _store.complete_chore(
        chore_id=chore_id, kid_id=kid_obj["id"],
        chore_date=target_date.isoformat(),
        completed_by=acted_by, note=note,
    )
    return (
        f"✓ {kid_obj['name']} — chore {chore_id} marked done on "
        f"{target_date.isoformat()} [completion {completion['id']}]"
    )


def uncomplete_chore(kid: str, chore: str, acted_by: str, date: str = "") -> str:
    """Un-check a previously completed chore.

    Args:
        kid: Kid identifier.
        chore: Chore id (ch-XXXXXXXX) or fuzzy chore name.
        acted_by: Caller's username.
        date: Date the chore was due. Default: today.

    Ack: Undoing check-off...
    """
    from apps.chores import store as _store

    kid_obj = _resolve_kid(kid)
    if not kid_obj:
        return f"Kid not found: {kid!r}"
    if not _is_parent(acted_by) and kid_obj.get("user_id") != acted_by:
        return f"Only {kid_obj['name']} (or a parent) can uncomplete their chores."

    target_date = _resolve_date(date)
    if chore.startswith("ch-"):
        chore_id = chore
    else:
        match = _store.find_assignment_for_kid_by_name(
            kid_obj["id"], chore, target_date,
        )
        if not match:
            return f"Couldn't find a chore matching {chore!r} for {kid_obj['name']}."
        chore_id = match["chore_id"]

    removed = _store.uncomplete_chore(
        chore_id=chore_id, kid_id=kid_obj["id"],
        chore_date=target_date.isoformat(),
    )
    if not removed:
        return f"No completion to undo for {chore_id} on {target_date}."
    return f"☐ {kid_obj['name']} — undid check-off for {chore_id} on {target_date}."


# ===========================================================================
# Kid CRUD (parent-only)
# ===========================================================================

def add_kid(name: str, acted_by: str, color: str = "#888888",
            user_id: str = "", sort_order: int = 0,
            notify_morning: bool = True) -> str:
    """Add a kid to the chore rotation. Parent only.

    Args:
        name: Display name.
        acted_by: Caller's username.
        color: Hex color for the UI (default '#888888').
        user_id: Optional username to link for notifications.
        sort_order: Display order (default 0).
        notify_morning: Whether they receive the 9 AM push (default true).

    Ack: Adding kid...
    """
    from apps.chores import data as _dl
    if not _is_parent(acted_by):
        return "Only parents can add kids."
    kid = _dl.create_kid(
        name=name, color=color, sort_order=sort_order,
        user_id=user_id or None, notify_morning=notify_morning,
        by=acted_by,
    )
    from apps.chores.store import _emit
    _emit("kid.added", {"kid_id": kid["id"], "name": kid["name"]})
    return f"Added kid: {kid['name']} [{kid['id']}]"


def update_kid(kid: str, acted_by: str, name: str = "", color: str = "",
               user_id: str = "", sort_order: int = -1,
               notify_morning: int = -1, notify_evening: int = -1,
               active: int = -1) -> str:
    """Update fields on a kid. Parent only. Pass -1 to keep an int/bool field unchanged.

    Args:
        kid: Kid identifier.
        acted_by: Caller's username.
        name, color, user_id: New values, or "" to leave unchanged.
        sort_order: New sort order, or -1.
        notify_morning, notify_evening, active: 0=false, 1=true, -1=unchanged.

    Ack: Updating kid...
    """
    from apps.chores import data as _dl
    if not _is_parent(acted_by):
        return "Only parents can update kids."
    kid_obj = _resolve_kid(kid)
    if not kid_obj:
        return f"Kid not found: {kid!r}"
    fields: dict = {}
    if name:
        fields["name"] = name
    if color:
        fields["color"] = color
    if user_id:
        fields["user_id"] = user_id
    if sort_order != -1:
        fields["sort_order"] = sort_order
    if notify_morning != -1:
        fields["notify_morning"] = bool(notify_morning)
    if notify_evening != -1:
        fields["notify_evening"] = bool(notify_evening)
    if active != -1:
        fields["active"] = bool(active)
    if not fields:
        return "No changes provided."
    updated = _dl.update_kid(kid_obj["id"], by=acted_by, **fields)
    from apps.chores.store import _emit
    _emit("kid.updated", {"kid_id": updated["id"], "fields": list(fields.keys())})
    return f"Updated {updated['name']}: {', '.join(fields.keys())}"


def remove_kid(kid: str, acted_by: str) -> str:
    """Soft-delete a kid (preserves completion history). Parent only.

    Ack: Removing kid...
    """
    from apps.chores import data as _dl
    if not _is_parent(acted_by):
        return "Only parents can remove kids."
    kid_obj = _resolve_kid(kid)
    if not kid_obj:
        return f"Kid not found: {kid!r}"
    _dl.soft_delete_kid(kid_obj["id"], by=acted_by)
    from apps.chores.store import _emit
    _emit("kid.removed", {"kid_id": kid_obj["id"]})
    return f"Removed {kid_obj['name']} (soft delete). They remain in any zones until removed manually."


# ===========================================================================
# Zone CRUD (parent-only)
# ===========================================================================

def add_zone(name: str, acted_by: str, rotation_start: str = "",
             description: str = "", member_kids: str = "") -> str:
    """Create a new chore zone. Parent only.

    Args:
        name: Zone name (e.g. "Living Room").
        acted_by: Caller.
        rotation_start: YYYY-MM-DD anchor for rotation math. Default: today.
        description: Optional.
        member_kids: Comma-separated list of kid identifiers in rotation order.
            E.g. "kid-id1, kid-id2, kid-id3".

    Ack: Creating zone...
    """
    from apps.chores import data as _dl
    from apps.chores import store as _store
    if not _is_parent(acted_by):
        return "Only parents can add zones."
    start = rotation_start or _store.today_local().isoformat()
    zone = _dl.create_zone(name=name, rotation_start=start, description=description, by=acted_by)
    member_ids: list[str] = []
    if member_kids:
        for ident in [s.strip() for s in member_kids.split(",") if s.strip()]:
            k = _resolve_kid(ident)
            if not k:
                return f"Zone created [{zone['id']}], but kid {ident!r} not found — add members manually."
            member_ids.append(k["id"])
        _dl.set_zone_members(zone["id"], member_ids)
    from apps.chores.store import _emit
    _emit("zone.added", {"zone_id": zone["id"], "name": zone["name"],
                         "member_kid_ids": member_ids})
    return f"Created zone {zone['name']} [{zone['id']}] with {len(member_ids)} member(s)."


def update_zone(zone: str, acted_by: str, name: str = "",
                description: str = "", rotation_start: str = "",
                member_kids: str = "") -> str:
    """Update zone fields. Parent only.

    Args:
        zone: Zone id or name.
        acted_by: Caller.
        name, description, rotation_start: New values, "" to skip.
        member_kids: Comma-separated kid identifiers to REPLACE the rotation order.
            (Warning: changing members re-shuffles future assignments.)

    Ack: Updating zone...
    """
    from apps.chores import data as _dl
    if not _is_parent(acted_by):
        return "Only parents can update zones."
    z = _dl.get_zone(zone) if zone.startswith("cz-") else _dl.get_zone_by_name(zone)
    if not z:
        return f"Zone not found: {zone!r}"
    fields: dict = {}
    if name:
        fields["name"] = name
    if description:
        fields["description"] = description
    if rotation_start:
        fields["rotation_start"] = rotation_start
    if fields:
        _dl.update_zone(z["id"], by=acted_by, **fields)
    if member_kids:
        member_ids: list[str] = []
        for ident in [s.strip() for s in member_kids.split(",") if s.strip()]:
            k = _resolve_kid(ident)
            if not k:
                return f"Member {ident!r} not found."
            member_ids.append(k["id"])
        _dl.set_zone_members(z["id"], member_ids)
        fields["members"] = member_ids
    from apps.chores.store import _emit
    _emit("zone.updated", {"zone_id": z["id"], "fields": list(fields.keys())})
    return f"Updated zone {z['name']}: {', '.join(fields.keys())}"


def remove_zone(zone: str, acted_by: str) -> str:
    """Delete a zone and its chores. Parent only. Fails if completion history references the chores.

    Ack: Removing zone...
    """
    from apps.chores import data as _dl
    if not _is_parent(acted_by):
        return "Only parents can remove zones."
    z = _dl.get_zone(zone) if zone.startswith("cz-") else _dl.get_zone_by_name(zone)
    if not z:
        return f"Zone not found: {zone!r}"
    try:
        _dl.delete_zone(z["id"], by=acted_by)
    except Exception as e:
        return f"Couldn't delete zone (likely has completion history): {e}"
    from apps.chores.store import _emit
    _emit("zone.removed", {"zone_id": z["id"]})
    return f"Removed zone {z['name']}."


# ===========================================================================
# Chore CRUD (parent-only)
# ===========================================================================

def add_chore(zone: str, dow, name: str, acted_by: str,
              position: int = -1, note: str = "") -> str:
    """Add a chore slot to a zone.

    Args:
        zone: Zone id or name.
        dow: Day of week — int 0..6 (0=Sun) or name ("Tuesday", "Tue").
        name: Chore name (e.g. "Empty Trash").
        acted_by: Caller.
        position: 0-based slot. -1 = append to the end of that day.
        note: Optional note (e.g. "Thorough cleaning").

    Ack: Adding chore...
    """
    from apps.chores import data as _dl
    if not _is_parent(acted_by):
        return "Only parents can add chores."
    z = _dl.get_zone(zone) if zone.startswith("cz-") else _dl.get_zone_by_name(zone)
    if not z:
        return f"Zone not found: {zone!r}"
    try:
        dow_int = _parse_dow(dow)
    except ValueError as e:
        return str(e)
    pos = None if position == -1 else position
    chore = _dl.create_chore(zone_id=z["id"], dow=dow_int, name=name, note=note, position=pos, by=acted_by)
    from apps.chores.store import _emit
    _emit("chore.added", {
        "chore_id": chore["id"], "zone_id": chore["zone_id"],
        "dow": chore["dow"], "position": chore["position"], "name": chore["name"],
    })
    return (
        f"Added chore '{chore['name']}' to {z['name']} on {_dow_name(chore['dow'])} "
        f"(position {chore['position']}). [{chore['id']}]"
    )


def update_chore(chore_id: str, acted_by: str, name: str = "", note: str = "",
                 dow=None, position: int = -1, active: int = -1) -> str:
    """Update a chore. Parent only.

    Args:
        chore_id: ch-XXXXXXXX
        acted_by: Caller.
        name, note: New values, "" to skip.
        dow: New day (int or name), None to skip.
        position: New position, -1 to skip.
        active: 0=false, 1=true, -1=skip.

    Ack: Updating chore...
    """
    from apps.chores import data as _dl
    if not _is_parent(acted_by):
        return "Only parents can update chores."
    fields: dict = {}
    if name:
        fields["name"] = name
    if note:
        fields["note"] = note
    if dow is not None:
        try:
            fields["dow"] = _parse_dow(dow)
        except ValueError as e:
            return str(e)
    if position != -1:
        fields["position"] = position
    if active != -1:
        fields["active"] = bool(active)
    if not fields:
        return "No changes provided."
    updated = _dl.update_chore(chore_id, by=acted_by, **fields)
    if not updated:
        return f"Chore not found: {chore_id}"
    from apps.chores.store import _emit
    _emit("chore.updated", {"chore_id": chore_id, "fields": list(fields.keys())})
    return f"Updated chore {chore_id}: {', '.join(fields.keys())}"


def remove_chore(chore_id: str, acted_by: str) -> str:
    """Soft-delete a chore. Parent only. Old completions are preserved.

    Ack: Removing chore...
    """
    from apps.chores import data as _dl
    if not _is_parent(acted_by):
        return "Only parents can remove chores."
    if not _dl.soft_delete_chore(chore_id, by=acted_by):
        return f"Chore not found: {chore_id}"
    from apps.chores.store import _emit
    _emit("chore.removed", {"chore_id": chore_id})
    return f"Removed chore {chore_id} (soft delete)."
