-- seed_small.sql: 2 venues x 200 seats, 4 events, 800 event_seats, 50 users.
-- Every seat starts AVAILABLE. Safe to rerun: it starts by emptying every table.
-- Run with `make seed` (psql) or from tests (psycopg); it is plain SQL only.

TRUNCATE booking_items, bookings, event_seats, events, seats, venues, users
    RESTART IDENTITY CASCADE;

INSERT INTO users (name, email)
SELECT 'User ' || u, 'user' || u || '@example.com'
FROM generate_series(1, 50) AS u;

INSERT INTO venues (name)
SELECT 'Venue ' || v
FROM generate_series(1, 2) AS v;

-- Per venue: 4 sections x 5 rows (A-E) x 10 seats = 200 seats.
-- Venue 1 gets seat ids 1-200, venue 2 gets 201-400; VIP is the first 50 of each.
INSERT INTO seats (venue_id, section, row_label, seat_no)
SELECT v.id, s.section, chr(64 + r), n
FROM venues AS v
CROSS JOIN (VALUES (1, 'VIP'), (2, 'LOWER'), (3, 'UPPER'), (4, 'BALCONY')) AS s (ord, section)
CROSS JOIN generate_series(1, 5) AS r
CROSS JOIN generate_series(1, 10) AS n
ORDER BY v.id, s.ord, r, n;

-- Events 1 and 3 at venue 1, events 2 and 4 at venue 2, one week apart.
INSERT INTO events (venue_id, name, starts_at)
SELECT (e - 1) % 2 + 1, 'Event ' || e, timestamptz '2027-01-01 19:00+00' + (e - 1) * interval '7 days'
FROM generate_series(1, 4) AS e;

-- One row per seat of the event's venue; price by section.
INSERT INTO event_seats (event_id, seat_id, price)
SELECT e.id, s.id,
       CASE s.section
           WHEN 'VIP' THEN 150.00
           WHEN 'LOWER' THEN 90.00
           WHEN 'UPPER' THEN 60.00
           ELSE 40.00
       END
FROM events AS e
JOIN seats AS s ON s.venue_id = e.venue_id
ORDER BY e.id, s.id;
