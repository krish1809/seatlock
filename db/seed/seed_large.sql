-- seed_large.sql: 20 venues x 10,000 seats, 1000 * scale events, one event_seats
-- row per seat of the event's venue: 10,000,000 rows at scale 1, 1,000,000 at 0.1.
-- About 70% BOOKED, 5% HELD (future held_until), 25% AVAILABLE, at random.
--
-- psql only (uses a psql variable):  make seed-large SCALE=0.1
-- BOOKED rows here have no bookings rows behind them; this data set exists to
-- study read performance on event_seats, not the booking flow.

\if :{?scale}
\else
    \set scale 1
\endif

BEGIN;

TRUNCATE booking_items, bookings, event_seats, events, seats, venues, users
    RESTART IDENTITY CASCADE;

INSERT INTO users (name, email)
SELECT 'User ' || u, 'user' || u || '@example.com'
FROM generate_series(1, 1000) AS u;

INSERT INTO venues (name)
SELECT 'Arena ' || v
FROM generate_series(1, 20) AS v;

-- Per venue: 4 sections x 50 rows x 50 seats = 10,000 seats. Inserted in order,
-- so venue v owns seat ids (v-1)*10000+1 .. v*10000 (checked below).
INSERT INTO seats (venue_id, section, row_label, seat_no)
SELECT v, s.section, 'R' || lpad(r::text, 2, '0'), n
FROM generate_series(1, 20) AS v
CROSS JOIN (VALUES (1, 'VIP'), (2, 'LOWER'), (3, 'UPPER'), (4, 'BALCONY')) AS s (ord, section)
CROSS JOIN generate_series(1, 50) AS r
CROSS JOIN generate_series(1, 50) AS n
ORDER BY v, s.ord, r, n;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM seats WHERE id NOT BETWEEN (venue_id - 1) * 10000 + 1 AND venue_id * 10000) THEN
        RAISE EXCEPTION 'seat ids are not contiguous per venue';
    END IF;
END $$;

INSERT INTO events (venue_id, name, starts_at)
SELECT (e - 1) % 20 + 1, 'Event ' || e, timestamptz '2027-01-01 19:00+00' + (e - 1) * interval '1 day'
FROM generate_series(1, greatest(1, round(1000 * :scale))::int) AS e;

-- Rows are generated event by event (seat ids computed from the venue), so one
-- event's rows sit together on disk, as they would when an event is created.
-- random() lives in the inner query so it is evaluated once per row.
INSERT INTO event_seats (event_id, seat_id, price, status, held_by, held_until)
SELECT event_id, seat_id,
       CASE (seat_id - 1) % 10000 / 2500
           WHEN 0 THEN 150.00 WHEN 1 THEN 90.00 WHEN 2 THEN 60.00 ELSE 40.00
       END,
       CASE WHEN r < 0.70 THEN 'BOOKED' WHEN r < 0.75 THEN 'HELD' ELSE 'AVAILABLE' END,
       CASE WHEN r >= 0.70 AND r < 0.75 THEN 1 + (r * 1000000)::bigint % 1000 END,
       CASE WHEN r >= 0.70 AND r < 0.75 THEN now() + interval '1 day' + r * interval '1 day' END
FROM (
    SELECT e.id AS event_id, seat_id, random() AS r
    FROM events AS e
    CROSS JOIN LATERAL generate_series((e.venue_id - 1) * 10000 + 1, e.venue_id * 10000) AS seat_id
) AS g;

COMMIT;

-- VACUUM sets hint bits and the visibility map so the first measured queries do
-- not pay for that; ANALYZE gives the planner statistics for the new data.
-- (VACUUM cannot run inside the transaction above.)
VACUUM (ANALYZE);
