-- Per-user PRIMARY SURFACE — where this person mainly talks to Skipper.
--
-- WHY THIS IS A STORED PREFERENCE AND NOT A DETECTED ONE
-- Skipper cannot tell whether someone is "on Discord": nothing in the system tracks
-- Discord presence, and a DM waits until it is read regardless. So the question
-- "should this go to Discord?" is unanswerable by observation alone. It is answerable
-- by asking, once, and letting each person say how they actually use Skipper.
--
-- HOW IT IS USED (app_platform/voice_policy)
--   'web'     — the default. Discord becomes a delivery target only while that person
--               is actively using it: a short window refreshed by each message they
--               send from Discord. So Skipper answers where someone is talking without
--               DM-ing them for everything that happens while they are away.
--   'discord' — Discord is their conversation, so it always receives, with no window.
--
-- The web console is NOT affected by this setting. It always receives and always shows
-- the complete record from every surface; the preference only decides which ADDITIONAL
-- surfaces are worth sending to. Nothing here can cause a message to be lost.
--
-- Per-user (not per-household) on purpose: one member may live in Discord while another
-- never opens it, and a household-wide setting would be wrong for somebody either way.

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS primary_surface text NOT NULL DEFAULT 'web';

-- Only surfaces a person can actually hold a conversation on. Voice is deliberately
-- absent: the speaker is a SHARED device, so a voice turn is not attributable to an
-- individual and cannot be anyone's primary surface.
ALTER TABLE public.users
    DROP CONSTRAINT IF EXISTS users_primary_surface_check;
ALTER TABLE public.users
    ADD CONSTRAINT users_primary_surface_check
    CHECK (primary_surface IN ('web', 'discord'));
