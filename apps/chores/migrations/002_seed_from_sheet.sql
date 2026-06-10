-- Chores App — Seed example data
-- Spreadsheet rotation anchor: 2022-07-18
-- Kids in users table: kid1, kid2, kid3 (linked via kids.user_id)

-- ============================================================================
-- KIDS
-- ============================================================================

INSERT INTO kids (id, name, color, sort_order, user_id, notify_morning) VALUES
  ('kid-one',    'Kid One',   '#3b82f6', 0, 'kid1', TRUE),
  ('kid-two',    'Kid Two',   '#10b981', 1, 'kid2', TRUE),
  ('kid-three',  'Kid Three', '#f59e0b', 2, 'kid3', TRUE)
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- ZONES
-- ============================================================================

INSERT INTO zones (id, name, rotation_start, sort_order, description) VALUES
  ('cz-bathroom',  'Bathroom',         '2022-07-18', 0, 'Shared bathroom — rotates across all three kids.'),
  ('cz-bedone',    'Bedroom - Kid One',  '2022-07-18', 1, 'Kid One''s bedroom.'),
  ('cz-bedshared', 'Bedroom - Shared',   '2022-07-18', 2, 'Kid Two & Kid Three''s shared bedroom.')
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- ZONE MEMBERS (ordering matches the spreadsheet)
-- ============================================================================

INSERT INTO zone_members (zone_id, kid_id, position) VALUES
  ('cz-bathroom',  'kid-one',   0),
  ('cz-bathroom',  'kid-two',   1),
  ('cz-bathroom',  'kid-three', 2),
  ('cz-bedone',    'kid-one',   0),
  ('cz-bedshared', 'kid-two',   0),
  ('cz-bedshared', 'kid-three', 1)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- CHORES (dow: 0=Sun, 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat)
-- ============================================================================

-- BATHROOM (Tuesdays — thorough; Fridays — quick)
INSERT INTO chores (id, zone_id, dow, position, name, note) VALUES
  ('ch-bathtu0', 'cz-bathroom', 2, 0, 'Sink & Counter',        'Thorough cleaning.'),
  ('ch-bathtu1', 'cz-bathroom', 2, 1, 'Toilet',                'Thorough cleaning.'),
  ('ch-bathtu2', 'cz-bathroom', 2, 2, 'Vac & Mop Bathroom',    'Thorough cleaning.'),
  ('ch-bathfr0', 'cz-bathroom', 5, 0, 'Sink & Counter',        'Quick clean.'),
  ('ch-bathfr1', 'cz-bathroom', 5, 1, 'Toilet',                'Quick clean.'),
  ('ch-bathfr2', 'cz-bathroom', 5, 2, 'Vacuum floor & Shower', 'Quick clean.')
ON CONFLICT (id) DO NOTHING;

-- BEDROOM - Kid One
INSERT INTO chores (id, zone_id, dow, position, name, note) VALUES
  ('ch-b1mo0',  'cz-bedone', 1, 0, 'Laundry & Declutter',  ''),
  ('ch-b1we0',  'cz-bedone', 3, 0, 'Vacuum & Empty Trash', ''),
  ('ch-b1th0',  'cz-bedone', 4, 0, 'Dust & Clean Desk',    '')
ON CONFLICT (id) DO NOTHING;

-- BEDROOM - Shared (Kid Two & Kid Three)
INSERT INTO chores (id, zone_id, dow, position, name, note) VALUES
  ('ch-bsmo0', 'cz-bedshared', 1, 0, 'Vacuum',      ''),
  ('ch-bsmo1', 'cz-bedshared', 1, 1, 'Clean Desk',  ''),
  ('ch-bswe0', 'cz-bedshared', 3, 0, 'Laundry',     ''),
  ('ch-bswe1', 'cz-bedshared', 3, 1, 'Declutter',   ''),
  ('ch-bsth0', 'cz-bedshared', 4, 0, 'Dust',        ''),
  ('ch-bsth1', 'cz-bedshared', 4, 1, 'Empty Trash', '')
ON CONFLICT (id) DO NOTHING;
