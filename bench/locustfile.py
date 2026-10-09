"""Load test for SeatLock. Pick one user class per run (run_all.sh does):

  HotSeatUser    every user fights over the same 50 seats (VIP, event 1)
  RealisticUser  80% availability reads, 20% holds, spread over all events

Both expect the small seed (make seed) and short holds (HOLD_SECONDS=2) so that
seats keep freeing up and contention lasts the whole run.

A 409 on a hold is a correct answer (the seat was taken), so it counts as a
success in Locust; only unexpected status codes count as failures.
Successful holds are appended to HOLD_LOG (JSON lines) for verify_oversell.py.
Statistics are reset WARMUP_SECONDS after the start, so they cover only the
measured part of the run; the hold log keeps everything.
"""
import json
import os
import random

import gevent
from locust import FastHttpUser, constant, events, task

HOT_EVENT = 1
HOT_SEATS = list(range(1, 51))   # VIP section of event 1 in seed_small.sql
USERS = range(1, 51)             # the 50 seeded users
WARMUP_S = float(os.environ.get("WARMUP_SECONDS", "10"))

_hold_log = open(os.environ["HOLD_LOG"], "a") if os.environ.get("HOLD_LOG") else None


@events.test_start.add_listener
def schedule_stats_reset(environment, **kwargs):
    gevent.spawn_later(WARMUP_S, environment.stats.reset_all)


@events.quitting.add_listener
def close_hold_log(environment, **kwargs):
    if _hold_log:
        _hold_log.close()


def post_hold(client, event_id, seat_ids, user_id, name):
    with client.post(f"/events/{event_id}/holds", json={"user_id": user_id, "seat_ids": seat_ids},
                     name=name, catch_response=True) as r:
        if r.status_code == 201:
            r.success()
            if _hold_log:
                body = r.json()
                _hold_log.write(json.dumps({"event_id": event_id, "user_id": user_id,
                                            "seat_ids": body["seat_ids"], "held_until": body["held_until"]}) + "\n")
        elif r.status_code == 409:
            r.success()
        else:
            r.failure(f"HTTP {r.status_code}")


class HotSeatUser(FastHttpUser):
    wait_time = constant(0)  # closed loop: send the next request as soon as one finishes

    def on_start(self):
        self.user_id = random.choice(USERS)

    @task
    def hold_hot_seats(self):
        seats = random.sample(HOT_SEATS, random.randint(1, 3))
        post_hold(self.client, HOT_EVENT, seats, self.user_id, "hold [hot]")


class RealisticUser(FastHttpUser):
    wait_time = constant(0)

    def on_start(self):
        self.user_id = random.choice(USERS)
        self.seats = {}
        for event in self.client.get("/events", name="setup").json():
            seats = self.client.get(f"/events/{event['id']}/seats", name="setup").json()
            self.seats[event["id"]] = [s["seat_id"] for s in seats]

    @task(80)
    def browse_availability(self):
        event_id = random.choice(list(self.seats))
        self.client.get(f"/events/{event_id}/seats?status=available", name="availability")

    @task(20)
    def hold_some_seats(self):
        event_id = random.choice(list(self.seats))
        seats = random.sample(self.seats[event_id], random.randint(1, 4))
        post_hold(self.client, event_id, seats, self.user_id, "hold [mix]")
