-- Sample data for Campaign Command. Re-runnable: clears the two tables first.
USE campaign_command;

DELETE FROM campaigns;
DELETE FROM tasks;

INSERT INTO campaigns (name, channel, spend, revenue, impressions, clicks, day) VALUES
  ('Brand search',        'Paid search', 420.00, 1420.00,  52000, 2100, CURDATE() - INTERVAL 2 DAY),
  ('Retargeting 30d',     'Paid social', 610.00, 1180.00,  96000, 1750, CURDATE() - INTERVAL 2 DAY),
  ('Harvest newsletter',  'Email',       120.00,  980.00,  31000, 2400, CURDATE() - INTERVAL 2 DAY),
  ('Editorial: skincare', 'Organic',      40.00,  760.00,  18000,  900, CURDATE() - INTERVAL 2 DAY),
  ('Brand search',        'Paid search', 395.00, 1360.00,  49000, 1990, CURDATE() - INTERVAL 1 DAY),
  ('Retargeting 30d',     'Paid social', 590.00, 1120.00,  91000, 1680, CURDATE() - INTERVAL 1 DAY);

INSERT INTO tasks (title, campaign, owner, status, due_day, progress) VALUES
  ('Refresh Q4 paid search ad copy',   'Always-on search',  'Riya',  'doing', CURDATE() + INTERVAL 4 DAY,  65),
  ('Approve autumn social creative',   'Autumn social',     'Aisha', 'todo',  CURDATE() + INTERVAL 2 DAY,  15),
  ('Fix conversion tracking /pricing', 'Always-on search',  'Tom',   'doing', CURDATE() + INTERVAL 1 DAY,  80),
  ('Draft newsletter: harvest drop',   'Harvest email',     'Ben',   'todo',  CURDATE() + INTERVAL 6 DAY,   0),
  ('Pull event leads into the CRM',    'September events',  'Riya',  'done',  CURDATE() - INTERVAL 1 DAY, 100);
