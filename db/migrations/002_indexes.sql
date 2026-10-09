-- 002_indexes.sql: performance indexes, added after measuring without them
-- (bench/index_study.py, results in bench/results/index_study.csv).

-- Availability listing: WHERE event_id = ? AND status = 'AVAILABLE'.
-- Partial: only AVAILABLE rows are in it (about 25% in the large seed), so at
-- 10M rows it is 4x smaller than an index on (event_id, status) and reads the
-- same 83 buffers per query (index_study.csv, tier 10M).
CREATE INDEX IF NOT EXISTS idx_event_seats_available
    ON event_seats (event_id)
    WHERE status = 'AVAILABLE';

-- Expiry sweeper: WHERE status = 'HELD' AND held_until < now(). Only HELD rows
-- are indexed, so the sweeper does not scan the whole table every few seconds.
CREATE INDEX IF NOT EXISTS idx_event_seats_held_until
    ON event_seats (held_until)
    WHERE status = 'HELD';

-- "My bookings, newest first": WHERE user_id = ? ORDER BY created_at DESC.
-- Also serves as the index on the bookings.user_id foreign key.
CREATE INDEX IF NOT EXISTS idx_bookings_user_created
    ON bookings (user_id, created_at DESC);

-- Foreign key columns we join or look up on, and the index that already covers each:
--   event_seats.event_id      leading column of the primary key (event_id, seat_id)
--   booking_items.booking_id  leading column of the primary key (booking_id, seat_id)
--   booking_items (event_id, seat_id) for active items: booking_items_one_active_per_seat
--   seats.venue_id            leading column of UNIQUE (venue_id, section, row_label, seat_no)
--   seats.id (joined from event_seats.seat_id): primary key
-- No query joins on events.venue_id, bookings.event_id or event_seats.held_by,
-- so they get no index: each index slows down every write to its table.
