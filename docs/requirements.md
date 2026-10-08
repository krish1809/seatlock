# SeatLock requirements

## 1. Problem statement

When many people try to reserve the same seats at the same moment, three things go wrong:

- **Double booking.** Two requests both read a seat as available, then both mark it as
  taken. Both users are told they got the seat.
- **Abandoned holds.** A user holds seats and leaves. Unless the hold ends by itself,
  nobody else can get those seats.
- **Demand spikes.** When sales open, hundreds of requests arrive for the same few seats
  at once. The system has to stay correct under that load, and should stay fast.

SeatLock is a backend that solves these with PostgreSQL concurrency control and measures
what each approach costs.

## 2. Functional requirements

- **F1 Browse.** List events. For one event, list its seats with status and price,
  optionally only the available ones. A seat whose hold has expired counts as available.
- **F2 Hold.** A user holds 1 to 6 seats of one event for 5 minutes (shorter in tests).
  The hold is all-or-nothing: if any requested seat is unavailable, no seat is held.
- **F3 Confirm.** A user turns seats they currently hold into a booking. The request
  carries an idempotency key. It is rejected if any seat is not held by that user or the
  hold has expired. The seat's price at confirm time is stored with the booking.
- **F4 Cancel.** A user cancels a whole confirmed booking, and its seats become available
  again.
- **F5 Hold expiry.** A hold ends 5 minutes after it was made, with no action from the
  user. Other users can take the seat from that moment on. A background job also resets
  expired holds on a timer.

Users are identified by a `user_id` sent in the request. There is no login.

## 3. Non-functional requirements

Each line is a claim that a test or benchmark in this repo checks. "Every correct
strategy" means all hold strategies except `naive`, which is broken on purpose as the
baseline.

- **N1 No double booking.** With 500 concurrent hold requests for the same 50 seats, each
  seat has at most one successful holder, and no seat ever has two active bookings. This
  holds for every correct strategy.
- **N2 Idempotent confirm.** Sending the same confirm (same idempotency key) twice in a
  row, or 10 times in parallel, creates exactly one booking.
- **N3 No deadlocks.** Multi-seat holds never deadlock: 1,000 pairs of concurrent holds
  that request the same seats in opposite order produce zero deadlock errors
  (SQLSTATE 40P01).
- **N4 Availability query latency.** Listing an event's available seats stays fast with
  10 million seat rows. Target: TBD, set after it is measured in the index study.

## 4. Out of scope

Payments, login and authentication, a seat-map UI or any frontend, and notifications
(email, SMS, push).
