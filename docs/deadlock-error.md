# The deadlock, as PostgreSQL reported it

Command: `make deadlock` (runs `experiments/deadlock/reproduce.py`, then `fixed.py`), run on 2026-10-09.

## What the client received (reproduce.py, Part 1)

```
T2: locked seat 2, now asking for seat 1
T1: locked seat 1, now asking for seat 2
T1: got seat 2 and committed (the other one was the victim)

T2 was aborted. The full error from PostgreSQL:

ERROR:  deadlock detected
DETAIL:  Process 1906 waits for ShareLock on transaction 4886; blocked by process 1905.
Process 1905 waits for ShareLock on transaction 4885; blocked by process 1906.
HINT:  See server log for query details.
CONTEXT:  while locking tuple (0,1) in relation "event_seats"
SQLSTATE: 40P01
```

## What the server logged (`docker compose logs postgres`)

```
2026-10-09 03:30:31.531 UTC [1906] ERROR:  deadlock detected
2026-10-09 03:30:31.531 UTC [1906] DETAIL:  Process 1906 waits for ShareLock on transaction 4886; blocked by process 1905.
	Process 1905 waits for ShareLock on transaction 4885; blocked by process 1906.
	Process 1906: SELECT 1 FROM event_seats WHERE event_id = $1 AND seat_id = $2 FOR UPDATE
	Process 1905: SELECT 1 FROM event_seats WHERE event_id = $1 AND seat_id = $2 FOR UPDATE
2026-10-09 03:30:31.531 UTC [1906] HINT:  See server log for query details.
2026-10-09 03:30:31.531 UTC [1906] CONTEXT:  while locking tuple (0,1) in relation "event_seats"
2026-10-09 03:30:31.531 UTC [1906] STATEMENT:  SELECT 1 FROM event_seats WHERE event_id = $1 AND seat_id = $2 FOR UPDATE
```

## Reading it line by line

- **Process 1906 / 1905** are the two backend processes, one per connection (T2 and T1).
  Each transaction got a transaction id (4885, 4886) when it first locked a row.
- **"waits for ShareLock on transaction 4886"**: a row lock is not kept in a lock table.
  Postgres writes the locker's transaction id into the row itself. To wait for a locked
  row, a backend waits for the *transaction* that holds it to finish, by asking for a
  ShareLock on that transaction id. So "1906 waits for transaction 4886, held by 1905"
  means T2 is waiting for T1 to end, and the second line says T1 waits for T2. That is the cycle.
- **CONTEXT "while locking tuple (0,1)"**: the row T2 was trying to lock, at page 0, item 1
  of `event_seats`. That is seat 1 of event 1, the seat T1 locked first.
- **Who is the victim**: neither transaction can move, so after `deadlock_timeout` (1s by
  default) the waiting backend that runs the deadlock check aborts *itself*. Here it was
  1906 (T2). Its locks are released, so T1 gets seat 2 and commits.
- **SQLSTATE 40P01** (`deadlock_detected`): the code the application retries on. See
  `with_retries` in `app/db.py`.

## The numbers (bench/results/deadlocks.csv)

| variant | pairs | 40P01 errors |
| --- | --- | --- |
| unordered (A then B against B then A) | 1000 | 822 |
| ordered (seat ids sorted before locking) | 1000 | 0 |

Both runs used `deadlock_timeout = 100ms` so the 1,000 pairs finish quickly. That setting
changes how soon a deadlock is detected, not whether one happens.
