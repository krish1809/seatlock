# Design decisions

Each decision lists the alternative that was considered and why it was rejected.

## Schema

### Why `event_seats` exists
A seat (`seats`) is physical and belongs to a venue; it is the same seat for every
show. Whether it is free, held or booked depends on the event, so that state needs
one row per (event, seat). `event_seats` is that row, and it is the only row a hold
has to lock, which keeps contention small and well defined.
**Alternative:** put status columns on `seats`. Rejected: a seat could then only be
sold for one event at a time. **Alternative:** no state table, derive availability
from `booking_items`. Rejected: holds would need their own table, and "is this seat
free?" would become a query over two tables with nothing single to lock.

### Why price is on `event_seats`
The same seat can cost different amounts at different shows (a final versus a
group-stage match). Price depends on the (event, seat) pair, so it belongs with the
key that determines it.
**Alternative:** price per section on `events`, or per seat on `seats`. Rejected:
per-section prices cannot express per-seat pricing, and a price on `seats` cannot
differ between events.

### Why `booking_items.price` is a snapshot
A booking records what the customer agreed to pay. If the organiser later changes
`event_seats.price`, past bookings must not change. Copying the price at confirm time
makes it a historical fact of the booking, not a derived value.
**Alternative:** join to `event_seats.price` when reading a booking. Rejected: that
rewrites history whenever a price changes.

### Is the schema in 3NF?
Almost. Every non-key column depends on the whole key and only on the key, with one
deliberate exception: `booking_items.event_id` is determined by `booking_id` alone
(through `bookings.event_id`), a partial dependency on the composite key
`(booking_id, seat_id)`, which breaks 2NF and so 3NF. It is kept because it enables
two constraints: the composite foreign key `(event_id, seat_id) -> event_seats`
(an item can only reference a seat that exists for that event) and the partial unique
index on `(event_id, seat_id) WHERE cancelled_at IS NULL`, which stops a double
booking even if the application has a bug. The price snapshot is not a violation,
because it records the price at a point in time rather than duplicating the current one.
**Alternative:** drop the column and stay in 3NF. Rejected: the database could then no
longer enforce "one active booking per seat", which is the property the project exists for.
**Known gap:** nothing checks that `booking_items.event_id` equals `bookings.event_id`,
or that an `event_seats` seat belongs to the event's venue. Both could be enforced with
extra composite foreign keys; the application writes them consistently instead.

### Surrogate `BIGINT` identity keys
`GENERATED ALWAYS AS IDENTITY` keys are small, never change, and make foreign keys cheap.
**Alternative:** natural keys such as `(venue_id, section, row_label, seat_no)` for seats.
Rejected: every referencing table would carry four columns. The natural key is still
enforced with a `UNIQUE` constraint.

## Holding seats

### A hold is a row state, not an open transaction
A hold sets `status = 'HELD'`, `held_by` and `held_until` and commits immediately.
Nothing stays locked between requests.
**Alternative:** keep a transaction open with the rows locked until the user confirms.
Rejected: every user would pin a pooled connection for minutes (the pool runs out
after `DB_POOL_SIZE` users), a user who walks away keeps the lock until the connection
dies, and HTTP requests cannot share a transaction anyway.

### One global lock order: ascending `seat_id`
Every path that locks several seats (holds, confirm, cancel, best-available) locks them
in ascending `seat_id`. Two transactions that both need seats 3 and 7 both ask for 3
first, so one simply waits for the other and no wait cycle can form.
**Alternative:** lock in request order and rely on deadlock detection plus retry.
Rejected: in `bench/results/deadlocks.csv` 822 of 1,000 opposing pairs deadlocked with
unordered locking and 0 of 1,000 with sorted ids. Every deadlock costs a
`deadlock_timeout` wait (1 s by default) plus a retry.

### Five strategies behind one interface
`HoldStrategy.hold(conn, event_id, seat_ids, user_id)`. The service (`app/services/holds.py`)
owns the transaction, the retries and the rollback, so a strategy contains only its
locking idea and the strategies can be compared on equal terms.
**Alternative:** each strategy manages its own transaction. Rejected: retry and
all-or-nothing logic would be repeated five times, slightly differently.

### All-or-nothing by rolling back the whole attempt
A strategy returns `success=False` and the service raises `psycopg.Rollback`, which
undoes any seat the attempt already changed.
**Alternative:** have each strategy undo its own partial work. Rejected: compensating
writes are easy to get wrong; a rollback cannot be.

### Optimistic: `WHERE version = <read>` without `status = 'AVAILABLE'`
Every write to `event_seats` bumps `version`, so an unchanged version proves the row is
exactly as read, including the status and `held_until` that were checked.
**Alternative:** `WHERE status = 'AVAILABLE' AND version = ...` as first sketched.
Rejected: a seat whose hold expired still says `HELD`, so it could never be taken.

### Conditional: lock in a CTE `ORDER BY seat_id`, then update
A plain multi-row UPDATE locks rows in the order its plan visits them. After
`002_indexes.sql` the planner switched that UPDATE from an index scan to a bitmap heap
scan (physical order), and `tests/test_concurrency.py` caught it. The CTE
(`SELECT ... ORDER BY seat_id FOR UPDATE`) fixes the order whatever the plan.
**Alternative:** one UPDATE per seat. Rejected: one round trip per seat, and it is
really the optimistic strategy without the version check.

### Serializable: the naive code at `SERIALIZABLE`, retried
Shows that the isolation level alone can make racy code correct, at the price of
40001 aborts and retries.
**Alternative:** `REPEATABLE READ`. Rejected: it stops lost updates on one row but not
write skew across rows (see `docs/isolation-results.md`).

### Retries: 3 times on 40001 and 40P01, full jitter
Both SQLSTATEs mean "rolled back, try again". Random backoff up to 10, 20, 40 ms keeps
retrying transactions from colliding again in lockstep. After 3 retries the client gets
a 409.
**Alternative:** no retries (clients see avoidable errors) or unlimited retries (one hot
seat can keep a request busy forever).

### `lock_timeout` 2 s, mapped to 409
A request waits at most 2 s for a row lock, then fails with 55P03 and a clean 409.
**Alternative:** wait indefinitely. Rejected: a slow transaction would stall every
request queued behind it and hold their pooled connections.

## Booking flow

### Idempotency with `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING`
The unique constraint decides which request wins, inside the database. A second request
with the same key waits for the first to commit, gets no row back, and returns the
existing booking with 200.
**Alternative:** `SELECT` the key first, then `INSERT`. Rejected: two parallel requests
can both see "not there" and both insert (the classic check-then-act race).
`tests/test_idempotency.py` sends the same key 10 times in parallel.
A reused key with a *different* body also returns the original booking unchanged; the
client is expected to send a new key for a new booking.

### Expiry: lazy on write, plus a sweeper with `SKIP LOCKED`
Every strategy treats `held_until < now()` as free, so correctness never depends on a
timer. The sweeper only resets expired rows so listings show them. It uses
`FOR UPDATE SKIP LOCKED`, so it never waits for, or deadlocks with, a request.
**Alternative:** only a periodic job releases holds. Rejected: a seat would stay
unavailable for up to one interval after its hold ended. **Alternative:** `pg_cron`.
Rejected: an extra extension for what one thread does.

### The availability listing filters on `status = 'AVAILABLE'` only
So it can use the partial index `idx_event_seats_available`. An expired hold shows up in
the listing after the next sweep (every 5 s by default).
**Alternative:** `status = 'AVAILABLE' OR (status = 'HELD' AND held_until < now())`.
Rejected: rows matched by the second branch are by definition not in the partial index,
so the query could no longer be answered from that index alone.

### Best available with `FOR UPDATE SKIP LOCKED`
Concurrent "give me 2 seats in VIP" requests take different seats instead of queueing
behind each other's locks (`tests/test_best_available.py`).
**Alternative:** `FOR UPDATE` without `SKIP LOCKED`. Rejected: every request would wait
for the same first rows.

## Indexes

### Partial index `(event_id) WHERE status = 'AVAILABLE'`
At 10M rows it makes the `event_seats` scan 0.31 ms / 83 buffers versus 1.458 ms / 120
buffers with only the primary key, and it is 17.8 MB versus 71.6 MB for an index on
`(event_id, status)` with the same speed (`bench/results/index_study.csv`).
**Alternative:** the plain composite index. Rejected: four times larger, and every status
change writes a new entry into it; the partial index only gets a new entry when a row
becomes `AVAILABLE`.

### No index for foreign keys that are already covered
`event_seats.event_id`, `booking_items.booking_id` and `seats.venue_id` are leading
columns of an existing key; see the comment in `002_indexes.sql`.
**Alternative:** index every foreign key column. Rejected: each index slows every write
to the contended table and none would be used.

## Testing and experiments

### Tests use a separate database (`seatlock_test`) on the real server
**Alternative:** the dev database, or SQLite. Rejected: tests would wipe the data the
benchmarks use, and SQLite has different locking, so it cannot test any of this.

### Isolation runner orders steps with `pg_blocking_pids()`, not sleeps
After each step it waits until the statement either finished or is blocked on a lock.
**Alternative:** `sleep()` between steps. Rejected: timing-based ordering is flaky on a
busy machine and hides which step actually blocked.

### Benchmark holds last 2 s, and oversell is measured as overlapping hold windows
With 5-minute holds the 50 hot seats sell out in the first second and the rest of the
run measures only 409s. With 2-second holds seats keep freeing up and contention lasts
the whole run. A legitimate re-hold can only start after the previous `held_until`, so
two successful holds whose windows overlap are a double booking.
**Alternative:** "more than one successful hold per seat". Rejected: with expiring
holds a seat is legitimately held many times in a run.

## Application

### Synchronous FastAPI endpoints with a psycopg `ConnectionPool`
Each request runs in a worker thread with one pooled connection and one short
transaction. This is easy to read and to test with plain threads.
**Alternative:** `async` endpoints with `AsyncConnectionPool`. Rejected for this
project: same SQL, more concepts to explain, and the database work is the subject.

### Fixed-size pool (`min_size = max_size`)
All connections are opened at startup, so a load spike never waits for new connections.
**Alternative:** a growing pool. Rejected: the first requests of a spike would pay for
connecting, which skews benchmarks.
