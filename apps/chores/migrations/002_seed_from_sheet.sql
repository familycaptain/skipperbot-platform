-- Chores App — Seed data from the Chore Manager Google Sheet
-- Spreadsheet rotation anchor: 2022-07-18
-- Kids in users table: kid1, kid2, kid3 (linked via kids.user_id)

-- ============================================================================
-- KIDS
-- ============================================================================

INSERT INTO kids (id, name, color, sort_order, user_id, notify_morning) VALUES
  ('kid-jacob000',  'Kid One',   '#3b82f6', 0, 'kid1',  TRUE),
  ('kid-elijah00',  'Kid Two',   '#10b981', 1, 'kid2', TRUE),
  ('kid-caleb000',  'Kid Three', '#f59e0b', 2, 'kid3',  TRUE)
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- ZONES
-- ============================================================================

INSERT INTO zones (id, name, rotation_start, sort_order, description) VALUES
  ('cz-bathroom', 'Bathroom',         '2022-07-18', 0, 'Shared bathroom — rotates across all three boys.'),
  ('cz-bedjacob', 'Bedroom - Kid One',  '2022-07-18', 1, 'Kid One''s bedroom.'),
  ('cz-bedec',    'Bedroom - Shared',   '2022-07-18', 2, 'Kid Two & Kid Three''s shared bedroom.')
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- ZONE MEMBERS (ordering matches the spreadsheet)
-- ============================================================================

INSERT INTO zone_members (zone_id, kid_id, position) VALUES
  ('cz-bathroom', 'kid-jacob000', 0),
  ('cz-bathroom', 'kid-elijah00', 1),
  ('cz-bathroom', 'kid-caleb000', 2),
  ('cz-bedjacob', 'kid-jacob000', 0),
  ('cz-bedec',    'kid-elijah00', 0),
  ('cz-bedec',    'kid-caleb000', 1)
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
  ('ch-bjmo0',  'cz-bedjacob', 1, 0, 'Laundry & Declutter',  ''),
  ('ch-bjwe0',  'cz-bedjacob', 3, 0, 'Vacuum & Empty Trash', ''),
  ('ch-bjth0',  'cz-bedjacob', 4, 0, 'Dust & Clean Desk',    '')
ON CONFLICT (id) DO NOTHING;

-- BEDROOM - E & C
INSERT INTO chores (id, zone_id, dow, position, name, note) VALUES
  ('ch-becmo0', 'cz-bedec', 1, 0, 'Vacuum',      ''),
  ('ch-becmo1', 'cz-bedec', 1, 1, 'Clean Desk',  ''),
  ('ch-becwe0', 'cz-bedec', 3, 0, 'Laundry',     ''),
  ('ch-becwe1', 'cz-bedec', 3, 1, 'Declutter',   ''),
  ('ch-becth0', 'cz-bedec', 4, 0, 'Dust',        ''),
  ('ch-becth1', 'cz-bedec', 4, 1, 'Empty Trash', '')
ON CONFLICT (id) DO NOTHING;
