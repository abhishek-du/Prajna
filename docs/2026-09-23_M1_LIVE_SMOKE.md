# M1 — first live contact with the Upstox V3 feed (2026-09-23)

**When:** 13:35–13:42 IST, during the **normal** market session, NOT pre-open.
**Account:** `2UB7PH`. **Token:** minted 13:33 IST via `prajna upstox login`, on the user's instruction.
**Code:** recorder as of `eeac6d1`, plus the watchdog fix committed with this note.
**Database:** none of these runs wrote rows. Every result below comes from the
archives, which are gitignored and live under
`backend/var/archive/UPSTOX_WS_V3/2026/09/23/`.

| Archive | Mode sent | Keys | Frames | stream_sha256 (prefix) |
|---|---|---|---|---|
| `preopen_2026-09-23_080536Z.frames.gz` | `full` | 5 | 60 | `589f3ebf3676023f` |
| `preopen_2026-09-23_080738Z.frames.gz` | `full_d30` | 5 | 4 | `90b49d2744f5d0c9` |
| `preopen_2026-09-23_080926Z.frames.gz` | `full` | 3,525 | 400 | `099f30c5edf58535` |
| `preopen_2026-09-23_081059Z.frames.gz` | `full` | 2,000 (conn A) | 200 | `229af0d101634d28` |
| `preopen_2026-09-23_081101Z.frames.gz` | `full` | 1,525 (conn B, concurrent) | 200 | `407314ff06934d7a` |

The universe came from instrument master sha256 `bf4a5db8…ba12331`, which has
80,226 rows and 3,525 eligible instruments (INE 3,172 / INF 351 / IN9 2).

## Findings

**B6 — mode wire string: RESOLVED.** The subscribe message `"mode": "full"`
comes back as `Feed.requestMode = full_d5`, with 5 book rungs on every tick
(19,474 ticks checked).

**B3 — full_d30: evidence says NO (inferred).** A `full_d30` subscription
received `market_info` and then **nothing** for any key, across 4 connections,
with no error frame and no close code. Upstox ignores it silently. The most
likely reading is that the account lacks Plus. This is not an explicit vendor
statement.

**B5 — subscription cap: RESOLVED for this account, on this date.**
- **The cap is 2,000 keys per connection in `full` mode, enforced silently.**
  3,525 keys were sent in 8 subscribe messages of ≤500. The first 4 messages
  (2,000 keys) received `initial_feed`; the other 1,525 received nothing, with
  no error.
- **The cap is per connection, not per user.** Two concurrent connections
  (2,000 + 1,525) were both fully served: 3,525 of 3,525 keys seen, and 0
  never-seen on either connection.
- **Consequence:** the whole eligible universe fits in 2 connections. With a
  single connection, sort-then-cap excludes all 351 INF ETFs, because keys sort
  as IN9 < INE < INF.
- **Not tested:** more than 2 concurrent connections, and whether the limit
  differs during pre-open.

**B8 — IEP/IEQ/IIQ population: still OPEN.** During the normal session `iep`,
`ieq`, `iiqTotal`, `iiqM` and `rp` were 0 on every tick, as expected outside
pre-open. `LTPC.iep` was absent. This needs the 09:00–09:15 window.

**B7 — iiqM semantics: still OPEN** (same reason).

**Other observations**
- **Latency:** receipt minus `currentTs` was 11–148 ms (median ~16 ms).
- **Frame size:** frames reached **160,929 bytes** with 2,000 keys; the
  websockets default 1 MiB limit is not hit.
- **Session status:** `segmentStatus` reported `NORMAL_OPEN` for 11 segments.
  `preOpenSessionStatus` was empty (normal session).
- **Parsing:** no schema drift and no parse issues on any frame.

## Network risk (new)

Before connecting, the first test failed 4 times:
- 2× `SSL: CERTIFICATE_VERIFY_FAILED — Hostname mismatch, certificate is not valid for 'wsfeeder-api.upstox.com'`
- 2× `Connection reset by peer`

The 5th attempt succeeded, about 36 s later. When checked directly, all three
resolved IPs (13.205.119.172, 3.110.1.70, 43.204.76.238) served a valid Amazon
`*.upstox.com` certificate. Earlier the same day `pip` reported a
"self-signed certificate in certificate chain".

Reading: something on the local network (DNS `192.168.0.20`) intermittently
intercepts TLS. TLS verification was **not** relaxed. On a pre-open morning,
the same pattern would cost the capture ~30–40 s of the 09:00–09:15 window.
Worth raising with whoever runs the network, or starting the capture earlier
than 08:55.

## Bug found and fixed

The watchdog reset on any frame, and a connection counted as productive once it
had delivered any frame. With a silently ignored subscription, the only frame is
`market_info`, so the recorder would have reconnected every `stale_after`
forever and never given up. Now both the watchdog and the failure-count reset
key on frames that carry a **subscribed** key. Covered by
`test_silently_ignored_subscription_still_gives_up`.
