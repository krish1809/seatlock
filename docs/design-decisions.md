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
