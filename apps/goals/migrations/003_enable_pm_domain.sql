-- Enable the PM thinking domain by default.
--
-- PM is the daily Project-Manager reasoning cycle: it reviews goals/projects/
-- tasks, talks to users about the work they own, and (for Skipper-owned goals)
-- drives Skipper to take action. It was seeded DISABLED in 002 (the old
-- enabled_by_default: false). The manifest now declares enabled_by_default:
-- true, but the loader's thinking-domain registration is still a stub, so this
-- migration is what actually flips the switch — for both fresh installs (002
-- seeds it disabled, this enables it) and existing installs (e.g. the Pi).
--
-- Runs once. A user can still disable PM later via the Thinking app; this does
-- not fight that (it only sets the out-of-the-box default at deploy time).
--
-- thinking_domains lives in the public schema (platform infra), so target it
-- explicitly regardless of the app search_path.

UPDATE public.thinking_domains SET enabled = true WHERE name = 'pm';
