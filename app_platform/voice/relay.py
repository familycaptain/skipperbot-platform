"""Server-side OpenAI Realtime relay (voice satellite ↔ host ↔ OpenAI).

The original design streamed audio satellite→OpenAI directly. This relay flips
that: the platform holds the OpenAI Realtime session (server-side, with the
platform's key), and the satellite becomes a thin audio endpoint (wake word +
AEC + 2-way PCM). The platform runs the tools, logs the transcript, and is the
single point where speaker identification will hook in (it sees the inbound
audio). Tools never round-trip to the satellite anymore — they execute here.

Satellite ↔ host WebSocket protocol (this module's side):
  satellite → host:
    * binary frame  = mic PCM16 mono @ REALTIME_AUDIO_RATE
    * text  frame   = JSON control: {"type": "end"}  (client-initiated stop)
  host → satellite:
    * binary frame  = output PCM16 mono @ REALTIME_AUDIO_RATE (play it)
    * text  frame   = JSON: {"type":"transcript","role":..,"text":..}
                      {"type":"status","status":"speech_started|stopped|ready"}
                      {"type":"session_ended"}

The OpenAI event flow mirrors the satellite's proven client
(skipperbot-voice/realtime_voice_test.py) exactly, so the two stay protocol-
compatible.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os

import websockets
from websockets.exceptions import ConnectionClosed

from config import logger

# SECURITY: the websockets client logs the full WS handshake — including the
# "Authorization: Bearer <OPENAI_API_KEY>" header — at DEBUG level. If the app
# runs at DEBUG, that leaks the key into the logs. Cap the library's own loggers
# to WARNING so the handshake (and the per-frame audio spam) never log, no
# matter what the platform's root log level is.
for _noisy in ("websockets", "websockets.client", "websockets.server", "websockets.protocol"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logging.getLogger("websockets").propagate = False
from app_platform.voice.session import (
    OPENAI_API_KEY,
    REALTIME_AUDIO_RATE,
    REALTIME_MODEL,
    REALTIME_VOICE,
)

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"

# Session voice-lock: once the first speaker is captured, later turns must match
# their voiceprint by at least this cosine similarity to be answered; everyone
# else (background voices, adjacent rooms) is ignored until "goodbye". Same
# speaker on the same mic typically scores well above this; a different person
# falls below. Tunable via env.
_LOCK_THRESHOLD = float(os.getenv("VOICE_SPEAKER_LOCK_THRESHOLD", "0.65"))
# Speaker-ID is ATTRIBUTION, not a gate on whether Skipper replies. By default the relay
# FAILS OPEN — it answers every turn and only uses the voiceprint to label the speaker.
# Set VOICE_SPEAKER_LOCK_STRICT=1 to restore the old behavior (silently drop turns whose
# voiceprint doesn't match the lock) — that made voice eat the user's own turns when the
# cosine similarity dipped (the "listening/thinking, no You:" bug), so it's off by default.
_LOCK_STRICT = os.getenv("VOICE_SPEAKER_LOCK_STRICT", "").strip().lower() in ("1", "true", "yes", "on")

_AUDIO_DELTA_TYPES = {"response.audio.delta", "response.output_audio.delta"}
_ASSISTANT_TRANSCRIPT_TYPES = {
    "response.audio_transcript.done",
    "response.output_audio_transcript.done",
}


def _session_update(instructions: str, tools: list[dict], voice: str) -> dict:
    """Build the OpenAI session.update payload (matches session.py / the satellite)."""
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "instructions": instructions,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": REALTIME_AUDIO_RATE},
                    "transcription": {
                        "model": os.getenv("VOICE_REALTIME_TRANSCRIPTION_MODEL", "whisper-1"),
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": float(os.getenv("VOICE_VAD_THRESHOLD", "0.5")),
                        "prefix_padding_ms": int(os.getenv("VOICE_VAD_PREFIX_PADDING_MS", "300")),
                        "silence_duration_ms": int(os.getenv("VOICE_VAD_SILENCE_MS", "500")),
                        # The relay drives responses itself (see _on_user_turn) so it
                        # can resolve speaker-ID and inject the speaker before the model
                        # answers. interrupt_response stays on so hardware-AEC barge-in
                        # still truncates in-progress speech.
                        "create_response": False,
                        "interrupt_response": True,
                    },
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": REALTIME_AUDIO_RATE},
                    "voice": voice,
                },
            },
            "tools": tools,
        },
    }


# Appended to the model's instructions so it knows the speaker-note convention.
_SPEAKER_AWARENESS = (
    "\n\nThis voice session is locked to the one person who started it. The relay "
    "filters out every other voice in the room, so you are only ever hearing that "
    "one speaker. A 'System note' tells you who they are (recognized by voice); "
    "trust it, attribute the conversation to that person, and you may greet them by "
    "name. If the note says they are not recognized and they tell you their name or "
    "ask you to remember their voice (e.g. \"this is <name>\"), call enroll_voice."
)


def _speaker_context_item(name: str | None, role: str = "user") -> dict:
    """A conversation item telling the model who is speaking this turn.

    Sent as a `user`-role item by default: the Realtime API honors mid-session
    `system` items unreliably (they get ignored on later turns, and can even force
    text-only replies), whereas a user item right before the response is read
    consistently. The durable session prompt was minted before the speaker was
    known, so this restated-every-turn note is the model's real source of identity.
    """
    if name:
        text = (f"System note: The person now speaking has been recognized by voice as "
                f"{name.title()}. Treat this and the following turns as {name.title()} "
                f"until a different speaker is announced.")
    else:
        text = ("System note: The current speaker's voice is not recognized as an enrolled "
                "household member. Do not assume who they are. If they tell you their name "
                "and ask to be remembered, call enroll_voice.")
    return {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": role,
            "content": [{"type": "input_text", "text": text}],
        },
    }


async def _openai_connect(url: str, headers: dict):
    """websockets >=12 renamed extra_headers → additional_headers; support both."""
    try:
        return await websockets.connect(url, additional_headers=headers, max_size=None)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers, max_size=None)


async def _send_oai(oai, event: dict) -> None:
    await oai.send(json.dumps(event))


async def _apply_tool_events(oai, events: list[dict]) -> bool:
    """Translate handle_voice_tool_call() output into OpenAI WS sends.

    Returns True if the session should end (end_voice_session tool).
    """
    should_end = False
    for ev in events or []:
        et = ev.get("type")
        if et == "session_update":
            # switch_voice_app → reconfigure the live session (new app's tools)
            await _send_oai(oai, _session_update(
                ev.get("instructions", ""),
                ev.get("tools", []),
                ev.get("voice", REALTIME_VOICE),
            ))
        elif et == "tool_result":
            await _send_oai(oai, {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": ev.get("call_id", ""),
                    "output": ev.get("output", ""),
                },
            })
            await _send_oai(oai, {"type": "response.create"})
            try:
                from app_platform.voice import debug_log as _dl
                _dl.record("→ response.create (after tool result) — expecting a spoken reply", kind="resp")
            except Exception:
                pass
        elif et == "end_session":
            should_end = True
    return should_end


async def relay_session(satellite_ws, session_id: str, session: dict) -> None:
    """Bridge one satellite audio WebSocket to a server-side OpenAI Realtime session.

    `satellite_ws` is an already-accepted Starlette WebSocket. `session` is the
    record created by app_platform.voice.session (base_instructions/base_tools).
    """
    from app_platform.voice.tool_runtime import handle_voice_tool_call
    try:
        from app_platform.voice.chatlog import record_voice_transcript
    except Exception:  # chatlog is best-effort
        record_voice_transcript = None

    instructions = (session.get("base_instructions", "") or "") + _SPEAKER_AWARENESS
    tools = session.get("base_tools", []) or []
    voice = session.get("voice", REALTIME_VOICE)
    user_id = session.get("user_id", "")

    if not OPENAI_API_KEY:
        await satellite_ws.send_text(json.dumps({"type": "error", "error": "OPENAI_API_KEY not set on the platform"}))
        return

    url = f"{OPENAI_REALTIME_URL}?model={REALTIME_MODEL}"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}

    oai = await _openai_connect(url, headers)
    logger.info("VOICE-RELAY: session %s connected to OpenAI Realtime (user=%s, tools=%d)",
                session_id, user_id, len(tools))
    stop = asyncio.Event()

    try:
        await _send_oai(oai, _session_update(instructions, tools, voice))

        # --- per-turn audio capture for speaker identification ---
        from app_platform.voice import speaker_id, debug_log
        debug_log.install()              # mirror voice logs into the live debug stream
        speaker_id.warm()               # preload the encoder OFF the hot path (don't stall turn 1)
        debug_log.record(f"session {session_id[:12]} relay started (user={user_id})",
                         session=session_id[:12], kind="session")
        _SR = REALTIME_AUDIO_RATE
        # Rolling buffer of the most recent mic audio. We DON'T gate capture on the
        # OpenAI VAD events (they arrive over the network lagged vs the live mic
        # stream, so an event-gated window grabs mostly trailing silence). Instead we
        # always keep the last ~8s and snapshot it on speech_stopped; resemblyzer
        # trims the silence and embeds the voiced part.
        _ROLL_MAX = _SR * 2 * 8  # ~8s of int16 mono
        mic_roll = bytearray()
        last_utterance = {"pcm": b""}      # most recent ACCEPTED (locked-speaker) turn
        # Response lifecycle: we own response.create (server-VAD create_response is
        # off), so track whether one is generating and serialize turns, to never hit
        # conversation_already_has_active_response.
        resp_idle = asyncio.Event()
        resp_idle.set()
        turn_lock = asyncio.Lock()
        # The session voice-lock: the reference voiceprint (adapted toward the speaker
        # as accepted turns come in, so it stabilizes), the resolved identity, and the
        # number of turns blended into the reference.
        lock = {"vec": None, "name": None, "n": 0}
        last_item = {"id": None}            # id of the latest committed user item (for delete)
        # item_id -> Future[transcript]. The user transcript arrives on its own event,
        # but we only persist it once the turn is ACCEPTED — so the transcription
        # handler resolves the future and the accept path consumes it. Off-target
        # turns drop the future, so background voices never reach chat history/memory.
        transcript_futs: dict[str, asyncio.Future] = {}
        dropped_items: set[str] = set()  # item_ids ignored before their transcript arrived

        def _transcript_fut(item_id: str) -> asyncio.Future:
            fut = transcript_futs.get(item_id)
            if fut is None:
                fut = asyncio.get_running_loop().create_future()
                transcript_futs[item_id] = fut
            return fut

        def _spawn(coro):
            """Run a fire-and-forget coro without leaking 'task exception never
            retrieved' noise when the session socket closes mid-flight."""
            async def _runner():
                try:
                    await coro
                except (ConnectionClosed, asyncio.CancelledError):
                    pass
                except Exception as exc:
                    logger.warning("VOICE-RELAY: background task error: %s", exc)
            return asyncio.create_task(_runner())

        async def _embed(pcm: bytes):
            if not pcm:
                return None
            t0 = time.monotonic()
            try:
                v = await asyncio.to_thread(speaker_id.embed, pcm, _SR)
                debug_log.record(f"embed {'ok' if v is not None else 'none'} in {time.monotonic()-t0:.2f}s",
                                 session=session_id[:12], kind="timing")
                return v
            except Exception as exc:
                logger.warning("VOICE-RELAY: embed failed: %s", exc)
                return None

        async def _set_locked_identity(name: str | None, score: float, *, relock: bool) -> None:
            """Record the locked speaker's name, notify the satellite, attribute turns.

            The model is told separately, every turn, by _accept_and_reply."""
            lock["name"] = name
            if name:
                session["user_id"] = name  # tools/data/permissions follow the locked speaker
                logger.info("VOICE-RELAY: %s user_id=%s by voice (sim %.2f) [session %s]",
                            "locked to" if relock else "speaker identified as",
                            name, score, session_id[:12])
            else:
                logger.info("VOICE-RELAY: locked to unidentified voice; user_id=%s (no enrolled "
                            "profile matched) [session %s]", session.get("user_id", ""), session_id[:12])
            try:
                await satellite_ws.send_text(json.dumps(
                    {"type": "speaker", "name": name or "", "locked": True}))
            except Exception:
                pass
            # The model is (re)told who's speaking by _accept_and_reply, right before
            # each response — so identity survives across turns, not just this one.

        async def _adopt_name_if_unidentified(vec) -> None:
            """Still unnamed but a turn was accepted → re-check enrolled profiles.

            Catches the speaker enrolling mid-session, or a profile that only matches
            once the lock has adapted. Only fills in a missing name; never reassigns."""
            if lock["name"] is not None:
                return
            try:
                name, score = await asyncio.to_thread(speaker_id.identify_vec, vec)
            except Exception:
                return
            if name and lock["name"] is None:
                await _set_locked_identity(name, score, relock=False)

        async def _finalize_user_transcript(item_id: str) -> None:
            """For an ACCEPTED turn: wait for its transcript, then persist + display it."""
            if not item_id:
                return
            fut = _transcript_fut(item_id)
            try:
                text = await asyncio.wait_for(fut, timeout=8.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                text = ""
            finally:
                transcript_futs.pop(item_id, None)
            text = (text or "").strip()
            if not text:
                return
            if record_voice_transcript:
                await record_voice_transcript(session_id, "user", text, user_id=session.get("user_id", ""))
            try:
                await satellite_ws.send_text(json.dumps({"type": "transcript", "role": "user", "text": text}))
            except Exception:
                pass
            debug_log.record(f"You: {text}", session=session_id[:12], kind="you")

        async def _create_response() -> None:
            """Ask the model to reply. Cancel any in-flight response first and wait for
            it to end, so we never hit conversation_already_has_active_response."""
            if not resp_idle.is_set():
                debug_log.record("→ response.cancel (prior reply still active) — waiting…",
                                 session=session_id[:12], kind="resp")
                await _send_oai(oai, {"type": "response.cancel"})
                try:
                    await asyncio.wait_for(resp_idle.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    debug_log.record("⚠ prior response didn't go idle within 2s",
                                     session=session_id[:12], kind="resp")
            await _send_oai(oai, {"type": "response.create"})
            debug_log.record("→ response.create", session=session_id[:12], kind="resp")

        async def _accept_and_reply(pcm: bytes) -> None:
            """Accept this turn: it's the locked speaker. Reply now; persist transcript."""
            last_utterance["pcm"] = pcm
            item_id = last_item.get("id")
            # Restate who's speaking right before every reply. Identity lives only in
            # the live conversation (the durable prompt was minted before we knew the
            # speaker) and a one-shot note gets buried as the chat grows — so we
            # re-assert it each turn. Skip when speaker-ID is unavailable: we'd have
            # nothing real to assert and the "call enroll_voice" hint wouldn't work.
            if speaker_id.available():
                await _send_oai(oai, _speaker_context_item(lock["name"], role="user"))
            await _create_response()
            _spawn(_finalize_user_transcript(item_id))

        async def _on_user_turn(pcm: bytes) -> None:
            """Drive the turn's reply (server-VAD create_response is off, so we own it).

            First utterance establishes the session voice-lock and replies. Later turns
            reply ONLY if their voiceprint matches the lock; any other voice (background,
            adjacent rooms, other people) is ignored and its stray turn is deleted from
            the model's context (and never written to chat history). The lock holds until
            the session ends ("goodbye").

            Serialized via turn_lock so rapid/overlapping turns (e.g. the wake-word
            pre-roll burst) can't race response.create against each other.
            """
            async with turn_lock:
                await _handle_turn(pcm)

        async def _handle_turn(pcm: bytes) -> None:
            if not speaker_id.available():
                await _accept_and_reply(pcm)
                return

            # Not locked yet → this utterance establishes the lock, then we reply.
            if lock["vec"] is None:
                vec = await _embed(pcm)
                if vec is not None:
                    lock["vec"] = vec
                    lock["n"] = 1
                    try:
                        name, score = await asyncio.to_thread(speaker_id.identify_vec, vec)
                    except Exception:
                        name, score = None, 0.0
                    await _set_locked_identity(name, score, relock=True)
                else:
                    # Encoder still warming / utterance not embeddable yet — ANSWER ANYWAY
                    # and lock on a later turn. (Never make the user repeat themselves just
                    # because speaker-ID isn't ready.)
                    logger.info("VOICE-RELAY: first utterance not embedded yet; answering anyway, "
                                "will lock on a later turn [session %s]", session_id[:12])
                await _accept_and_reply(pcm)
                return

            # Locked. Speaker-ID is ATTRIBUTION, not a reply gate: a confident match adapts
            # the lock + keeps the identity; a low-confidence turn is STILL answered (fail-open),
            # just not blended into the reference. Old behavior (drop off-target turns) is opt-in
            # via VOICE_SPEAKER_LOCK_STRICT.
            locked_user = lock["name"] or "unidentified"
            vec = await _embed(pcm)
            sim = speaker_id.cosine(vec, lock["vec"]) if vec is not None else 0.0
            if vec is not None and sim >= _LOCK_THRESHOLD:
                # Adapt the reference toward the speaker (running average — cosine is
                # scale-invariant, so no renormalize needed). Stabilizes the lock and
                # pulls the speaker's own future sims up.
                n = lock["n"]
                lock["vec"] = [(o * n + x) / (n + 1) for o, x in zip(lock["vec"], vec)]
                lock["n"] = n + 1
                logger.info("VOICE-RELAY: turn accepted, user_id=%s (sim %.2f) [session %s]",
                            locked_user, sim, session_id[:12])
                # Resolve identity BEFORE replying (awaited, not spawned) so this very
                # turn's response already knows who they are — otherwise the reply goes
                # out as "unidentified" and recognition always lags a turn behind.
                if lock["name"] is None:
                    await _adopt_name_if_unidentified(vec)
                await _accept_and_reply(pcm)
                return

            # Low-confidence / unmatched turn.
            if _LOCK_STRICT:
                logger.info("VOICE-RELAY: [strict] ignoring off-target voice (sim %.2f < %.2f); "
                            "locked to user_id=%s [session %s]",
                            sim, _LOCK_THRESHOLD, locked_user, session_id[:12])
                item_id = last_item.get("id")
                if item_id:
                    await _send_oai(oai, {"type": "conversation.item.delete", "item_id": item_id})
                    dropped_items.add(item_id)  # its transcript may still be in flight
                    fut = transcript_futs.pop(item_id, None)
                    if fut and not fut.done():
                        fut.cancel()
                return
            logger.info("VOICE-RELAY: low-confidence voice (sim %.2f < %.2f) — answering anyway "
                        "(fail-open); not adapting the lock [session %s]",
                        sim, _LOCK_THRESHOLD, session_id[:12])
            await _accept_and_reply(pcm)

        async def pump_satellite_to_openai():
            """Mic PCM (binary) → OpenAI input_audio_buffer.append; text = control."""
            try:
                while not stop.is_set():
                    msg = await satellite_ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    chunk = msg.get("bytes")
                    if chunk:
                        await _send_oai(oai, {
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(chunk).decode("ascii"),
                        })
                        # Always roll the recent mic audio (independent of VAD events).
                        mic_roll.extend(chunk)
                        if len(mic_roll) > _ROLL_MAX:
                            del mic_roll[:len(mic_roll) - _ROLL_MAX]
                        continue
                    text = msg.get("text")
                    if text:
                        try:
                            ctrl = json.loads(text)
                        except json.JSONDecodeError:
                            continue
                        if ctrl.get("type") == "end":
                            break
            finally:
                stop.set()

        async def pump_openai_to_satellite():
            """OpenAI events → satellite audio/transcripts; tools run here."""
            try:
                async for raw in oai:
                    if stop.is_set():
                        break
                    event = json.loads(raw)
                    et = event.get("type", "")

                    if et in _AUDIO_DELTA_TYPES:
                        delta = event.get("delta", "")
                        if delta:
                            await satellite_ws.send_bytes(base64.b64decode(delta))

                    elif et == "response.created":
                        resp_idle.clear()
                        debug_log.record("← response.created (generating reply)", session=session_id[:12], kind="resp")
                    elif et in ("response.done", "response.cancelled"):
                        resp_idle.set()
                        debug_log.record(f"← {et}", session=session_id[:12], kind="resp")

                    elif et == "input_audio_buffer.speech_started":
                        await satellite_ws.send_text(json.dumps({"type": "status", "status": "speech_started"}))
                        debug_log.record("● speech started (listening)", session=session_id[:12], kind="vad")
                    elif et == "input_audio_buffer.speech_stopped":
                        await satellite_ws.send_text(json.dumps({"type": "status", "status": "speech_stopped"}))
                        debug_log.record("■ speech stopped (processing turn)", session=session_id[:12], kind="vad")
                        # Voice-lock check + drive the reply (response.create is issued in
                        # there, not by server-VAD). Snapshot the last ~8s of mic audio and
                        # run off the event loop so embed work doesn't stall the receive pump.
                        _spawn(_on_user_turn(bytes(mic_roll)))

                    elif et == "input_audio_buffer.committed":
                        # Remember the user item id so an off-target turn can be deleted.
                        last_item["id"] = event.get("item_id")

                    elif et == "conversation.item.input_audio_transcription.delta":
                        # Live partial transcript — stream words to the satellite "You:" line
                        # and the debug stream AS they're heard (don't wait for the full turn).
                        d = event.get("delta", "")
                        if d:
                            try:
                                await satellite_ws.send_text(json.dumps(
                                    {"type": "transcript_partial", "role": "user", "delta": d}))
                            except Exception:
                                pass
                            debug_log.record(d, session=session_id[:12], kind="you_partial")

                    elif et == "conversation.item.input_audio_transcription.completed":
                        # Hand the text to the turn's future; the accept path persists +
                        # displays it (off-target turns drop the future, so they're never
                        # recorded). Keyed by item_id so it pairs with the right turn.
                        item_id = event.get("item_id")
                        if item_id and item_id in dropped_items:
                            dropped_items.discard(item_id)  # ignored turn — never record it
                        elif item_id:
                            fut = _transcript_fut(item_id)
                            if not fut.done():
                                fut.set_result(event.get("transcript", ""))

                    elif et in _ASSISTANT_TRANSCRIPT_TYPES:
                        text = event.get("transcript", "")
                        if record_voice_transcript:
                            await record_voice_transcript(session_id, "assistant", text, user_id=session.get("user_id", ""))
                        await satellite_ws.send_text(json.dumps({"type": "transcript", "role": "assistant", "text": text}))
                        debug_log.record(f"Skipper: {text[:300]}", session=session_id[:12], kind="skipper")

                    elif et == "response.function_call_arguments.done":
                        call_id = event.get("call_id", "")
                        name = event.get("name", "")
                        raw_args = event.get("arguments") or "{}"
                        try:
                            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        except json.JSONDecodeError:
                            args = {}
                        logger.info("VOICE-RELAY: tool %s(%s) [session %s]", name, list(args.keys()), session_id[:12])
                        if name == "enroll_voice":
                            # Enrollment needs the audio, which only the relay has —
                            # use the just-spoken utterance. Handled here, not tool_runtime.
                            person = (args.get("name") or "").strip()
                            locked = lock["name"]
                            if locked and person and person.lower() == locked.lower():
                                # Already recognized as this person by voice. Don't
                                # re-enroll every session — just confirm. Defends the
                                # "model thinks you're a stranger" re-enroll loop even
                                # if the model still over-calls the tool.
                                out = (f"You're already enrolled, {person.title()} — "
                                       "I recognize your voice.")
                            else:
                                ok = False
                                if person and last_utterance["pcm"] and speaker_id.available():
                                    ok = await asyncio.to_thread(
                                        speaker_id.enroll, person, last_utterance["pcm"], _SR)
                                if ok and lock["name"] is None:
                                    # Newly enrolled mid-session → adopt the name so the
                                    # rest of the session (tools, data, the reply) is
                                    # attributed to them right away.
                                    await _set_locked_identity(
                                        person.strip().lower(), 1.0, relock=False)
                                out = (f"Got it — I'll recognize {person}'s voice from now on."
                                       if ok else
                                       "I couldn't capture a clear voice sample. Make sure voice "
                                       "recognition is set up, then say a full sentence and try again.")
                            await _apply_tool_events(oai, [
                                {"type": "tool_result", "call_id": call_id, "output": out}])
                        else:
                            _t0 = time.monotonic()
                            events = await handle_voice_tool_call(
                                session_id=session_id, call_id=call_id, tool_name=name, arguments=args,
                            )
                            _out = next((str(e.get("output", "")) for e in events
                                         if e.get("type") == "tool_result"), "")
                            debug_log.record(f"tool {name} returned in {time.monotonic()-_t0:.2f}s: {_out[:80]}",
                                             session=session_id[:12], kind="tool")
                            if await _apply_tool_events(oai, events):
                                break

                    elif et == "error":
                        logger.error("VOICE-RELAY: OpenAI error [session %s]: %s", session_id[:12], event.get("error"))
            finally:
                stop.set()

        await asyncio.gather(pump_satellite_to_openai(), pump_openai_to_satellite())
    finally:
        try:
            await oai.close()
        except Exception:
            pass
        try:
            await satellite_ws.send_text(json.dumps({"type": "session_ended"}))
        except Exception:
            pass
        logger.info("VOICE-RELAY: session %s relay closed", session_id)
