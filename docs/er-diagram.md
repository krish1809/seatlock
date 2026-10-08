# ER diagram

Source of truth: [db/migrations/001_schema.sql](../db/migrations/001_schema.sql).

```mermaid
erDiagram
    venues ||--o{ seats : "has"
    venues ||--o{ events : "hosts"
    events ||--o{ event_seats : "sells"
    seats  ||--o{ event_seats : "appears in"
    users  |o--o{ event_seats : "holds (held_by)"
    users  ||--o{ bookings : "makes"
    events ||--o{ bookings : "for"
    bookings ||--|{ booking_items : "contains"
    event_seats ||--o{ booking_items : "booked as"

    users {
        bigint id PK
        text name
        text email UK
        timestamptz created_at
    }
    venues {
        bigint id PK
        text name UK
    }
    seats {
        bigint id PK
        bigint venue_id FK "UK (venue_id, section, row_label, seat_no)"
        text section
        text row_label
        int seat_no
    }
    events {
        bigint id PK
        bigint venue_id FK
        text name
        timestamptz starts_at
    }
    event_seats {
        bigint event_id PK, FK
        bigint seat_id PK, FK
        text status "AVAILABLE | HELD | BOOKED"
        numeric price ">= 0"
        int version
        bigint held_by FK "set only when HELD"
        timestamptz held_until "set only when HELD"
    }
    bookings {
        bigint id PK
        bigint user_id FK
        bigint event_id FK
        text status "CONFIRMED | CANCELLED"
        text idempotency_key UK
        timestamptz created_at
    }
    booking_items {
        bigint booking_id PK, FK
        bigint seat_id PK, FK
        bigint event_id FK "FK (event_id, seat_id) -> event_seats"
        numeric price "snapshot"
        timestamptz cancelled_at
    }
```

`booking_items` also has a partial unique index on `(event_id, seat_id) WHERE cancelled_at IS NULL`:
at most one active booking per seat per event.
