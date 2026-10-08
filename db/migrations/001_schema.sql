-- 001_schema.sql: the seven SeatLock tables.
-- Only primary keys, unique constraints, checks and foreign keys live here.
-- Performance indexes come later (002), after measuring the queries without them.

CREATE TABLE users (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE venues (
    id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- A physical seat. It exists once per venue, whatever event is on.
CREATE TABLE seats (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue_id  BIGINT NOT NULL REFERENCES venues (id),
    section   TEXT NOT NULL,
    row_label TEXT NOT NULL,
    seat_no   INT NOT NULL CHECK (seat_no > 0),
    UNIQUE (venue_id, section, row_label, seat_no)
);

CREATE TABLE events (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue_id  BIGINT NOT NULL REFERENCES venues (id),
    name      TEXT NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL
);

-- One row per seat per event: the state of that seat for that show.
-- This is the contended table; every hold strategy reads and writes it.
CREATE TABLE event_seats (
    event_id   BIGINT NOT NULL REFERENCES events (id),
    seat_id    BIGINT NOT NULL REFERENCES seats (id),
    status     TEXT NOT NULL DEFAULT 'AVAILABLE'
               CHECK (status IN ('AVAILABLE', 'HELD', 'BOOKED')),
    price      NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    -- Bumped by every UPDATE of the row. The optimistic strategy compares it to
    -- detect that someone else changed the row since it was read.
    version    INT NOT NULL DEFAULT 0,
    held_by    BIGINT REFERENCES users (id),
    held_until TIMESTAMPTZ,
    PRIMARY KEY (event_id, seat_id),
    -- A row is HELD exactly when both hold fields are set, and no other row
    -- carries hold data. A hold is data in the row, never an open transaction.
    CONSTRAINT event_seats_hold_fields CHECK (
        (status = 'HELD' AND held_by IS NOT NULL AND held_until IS NOT NULL)
        OR (status <> 'HELD' AND held_by IS NULL AND held_until IS NULL)
    )
);

CREATE TABLE bookings (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users (id),
    event_id        BIGINT NOT NULL REFERENCES events (id),
    status          TEXT NOT NULL DEFAULT 'CONFIRMED'
                    CHECK (status IN ('CONFIRMED', 'CANCELLED')),
    -- Sent by the client. A retried confirm with the same key hits this
    -- constraint instead of creating a second booking.
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE booking_items (
    booking_id   BIGINT NOT NULL REFERENCES bookings (id),
    -- event_id repeats bookings.event_id on purpose: it is needed for the
    -- foreign key to event_seats and for the unique index below.
    event_id     BIGINT NOT NULL,
    seat_id      BIGINT NOT NULL,
    -- Price snapshot at confirm time; event_seats.price may change later.
    price        NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    cancelled_at TIMESTAMPTZ,
    PRIMARY KEY (booking_id, seat_id),
    FOREIGN KEY (event_id, seat_id) REFERENCES event_seats (event_id, seat_id)
);

-- Last line of defense against double booking: at most one non-cancelled
-- booking item per seat per event, whatever bug the application code has.
CREATE UNIQUE INDEX booking_items_one_active_per_seat
    ON booking_items (event_id, seat_id)
    WHERE cancelled_at IS NULL;
