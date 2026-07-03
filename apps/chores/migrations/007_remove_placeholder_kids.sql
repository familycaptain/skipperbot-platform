-- Chores App — Remove the placeholder kid1/2/3 seed from already-upgraded installs (ev-59).
--
-- Companion to the gutted 002_seed_from_sheet.sql. Fresh installs never seed the
-- placeholder household, but boxes that already ran the OLD 002 carry three
-- placeholder kids (Kid One/Two/Three, users kid1/kid2/kid3), two/three demo
-- zones (Bathroom / Bedroom - Kid One / Bedroom - Shared) and their chores.
-- This forward-only migration cleans them up.
--
-- SAFETY: the seed is a functional, ADOPTABLE starter household — a real family
-- may have renamed a placeholder kid, checked chores off, or added members. So
-- we remove the seed ONLY WHERE IT IS STILL AN UNTOUCHED PLACEHOLDER, and leave
-- an adopted household ENTIRELY intact. We never delete a family's real data and
-- never abort on the ON DELETE RESTRICT foreign keys (we simply do nothing when
-- the install shows any adoption).
--
-- Idempotent: keyed on the fixed seed ids; a re-run (or a fresh install that
-- never had the seed) is a no-op.

DO $$
DECLARE
  seed_kid_ids   text[] := ARRAY['kid-one','kid-two','kid-three'];
  seed_zone_ids  text[] := ARRAY['cz-bathroom','cz-bedone','cz-bedshared'];
  seed_chore_ids text[] := ARRAY[
    'ch-bathtu0','ch-bathtu1','ch-bathtu2',
    'ch-bathfr0','ch-bathfr1','ch-bathfr2',
    'ch-b1mo0','ch-b1we0','ch-b1th0',
    'ch-bsmo0','ch-bsmo1','ch-bswe0','ch-bswe1','ch-bsth0','ch-bsth1'
  ];
  untouched boolean;
BEGIN
  -- Is the install still a PRISTINE, unadopted seed? True only when:
  SELECT
    -- (a) every surviving seed kid still bears its exact seeded identity
    --     (unchanged name + user_id) — a rename means the family adopted it.
    NOT EXISTS (
      SELECT 1 FROM kids
      WHERE id = ANY(seed_kid_ids)
        AND (id, name, user_id) NOT IN (
          ('kid-one',   'Kid One',   'kid1'),
          ('kid-two',   'Kid Two',   'kid2'),
          ('kid-three', 'Kid Three', 'kid3')
        )
    )
    -- (b) zero chore_completions reference any seed kid or seed chore
    --     (a check-off is real usage history — keep it).
    AND NOT EXISTS (
      SELECT 1 FROM chore_completions
      WHERE kid_id = ANY(seed_kid_ids) OR chore_id = ANY(seed_chore_ids)
    )
    -- (c) no user-added kids beyond the seed.
    AND NOT EXISTS (
      SELECT 1 FROM kids WHERE NOT (id = ANY(seed_kid_ids))
    )
    -- (d) no user-added zone_members beyond the seed (a non-seed kid in any
    --     zone, or any member of a non-seed zone).
    AND NOT EXISTS (
      SELECT 1 FROM zone_members
      WHERE NOT (kid_id = ANY(seed_kid_ids)) OR NOT (zone_id = ANY(seed_zone_ids))
    )
    -- (e) no user-added zones beyond the seed.
    AND NOT EXISTS (
      SELECT 1 FROM zones WHERE NOT (id = ANY(seed_zone_ids))
    )
    -- (f) no user-added chores beyond the seed.
    AND NOT EXISTS (
      SELECT 1 FROM chores WHERE NOT (id = ANY(seed_chore_ids))
    )
  INTO untouched;

  IF untouched THEN
    -- FK-safe delete order (children first): chore_completions -> zone_members
    -- -> chores -> zones -> kids. All keyed on the fixed seed ids, so this is
    -- idempotent (re-run deletes nothing) and cannot touch non-seed rows.
    DELETE FROM chore_completions WHERE kid_id = ANY(seed_kid_ids) OR chore_id = ANY(seed_chore_ids);
    DELETE FROM zone_members      WHERE zone_id = ANY(seed_zone_ids) OR kid_id = ANY(seed_kid_ids);
    DELETE FROM chores            WHERE id = ANY(seed_chore_ids) OR zone_id = ANY(seed_zone_ids);
    DELETE FROM zones             WHERE id = ANY(seed_zone_ids);
    DELETE FROM kids              WHERE id = ANY(seed_kid_ids);
  END IF;
END $$;
