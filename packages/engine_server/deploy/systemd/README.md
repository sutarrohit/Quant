# systemd units

For a deployment without Docker. Three services, matching the three in
`docker-compose.yml` and for the same reasons: a backtest pins a CPU for
minutes, so it must not run inside the API process.

| Unit | Process | Needed for |
|---|---|---|
| `engine-api.service` | FastAPI. Validates and enqueues; never runs a backtest | always |
| `engine-worker@.service` | arq. Runs one backtest at a time | backtests |
| `engine-live.service` | Supervisor. Converges accounts on their desired state | live/paper only |

## Install

```bash
# 1. A user that owns nothing else.
sudo useradd --system --home /opt/engine-server --shell /usr/sbin/nologin nautilus

# 2. The code, and its venv.
sudo git clone <repo> /opt/engine-server
cd /opt/engine-server && sudo -u nautilus uv sync --frozen --no-dev

# 3. Data directories.
sudo install -d -o nautilus -g nautilus /var/lib/engine-server/{catalog,raw,artifacts,kill}

# 4. Configuration. 0600, because it holds the bearer token.
sudo install -m 0600 -o nautilus deploy/systemd/engine-server.env /etc/engine-server.env
sudo -e /etc/engine-server.env          # set NT_INTERNAL_API_KEY

# 5. The units.
sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now engine-api engine-worker@1 engine-worker@2
```

`engine-live` is enabled separately and deliberately — starting it is a decision
about trading, not about deploying:

```bash
sudo systemctl enable --now engine-live
```

## Two Redis instances, not two databases

Both units need `NT_REDIS_URL` and `engine-live` also needs
`NT_CACHE_REDIS_URL`, and they must be **different instances**. Nautilus's
`DatabaseConfig` exposes no database index (`docs/nautilus-api-notes.md` D15),
so `redis://localhost:6379/5` and `redis://localhost:6379/0` both land on
database 0 of the same server — and a `FLUSHDB` aimed at the queue would erase
live position state.

```bash
# The queue, on the default port.
sudo systemctl enable --now redis-server

# The live cache, a second instance on 6380.
sudo cp /etc/redis/redis.conf /etc/redis/redis-cache.conf
sudo sed -i 's/^port 6379/port 6380/; s/^pidfile.*/pidfile \/run\/redis\/redis-cache.pid/; \
             s/^dir .*/dir \/var\/lib\/redis-cache/; s/^dbfilename.*/dbfilename cache.rdb/' \
             /etc/redis/redis-cache.conf
sudo install -d -o redis -g redis /var/lib/redis-cache
sudo systemctl enable --now redis-server@redis-cache
```

`engine-live` refuses to start if either is unreachable, naming which one
(`PreflightFailed`). That is deliberate: `TradingNode` construction blocks
**forever** on an unreachable cache Redis and does not die on `SIGTERM` (D16),
so a deploy that fails is much better than one that wedges.

## Workers

`engine-worker@.service` is templated because each worker runs exactly one
backtest at a time. Scale by instance, one per core you are willing to give up:

```bash
sudo systemctl enable --now engine-worker@3 engine-worker@4
sudo systemctl stop engine-worker@4
```

## Stopping the live plane

`systemctl stop engine-live` sends `SIGTERM`, which stops the nodes, marks them
`STOPPED` and releases their leases — so a restart picks the accounts up within
seconds rather than after a 90-second heartbeat timeout. `TimeoutStopSec=30`
gives it room; a `SIGKILL` skips all of it, which is what the heartbeat timeout
exists to cover.

**To stop trading without stopping the process**, use the kill switch. It is the
faster and more targeted instrument, and it works when the API does not:

```bash
sudo -u nautilus touch /var/lib/engine-server/kill/kill-acct_1   # one account
sudo -u nautilus touch /var/lib/engine-server/kill/kill-all      # everything
```

**This is a total stop**: within seconds nothing reaches the venue, exits
included. You reach for a kill switch when you do not trust the strategy, and a
strategy you do not trust should not be closing positions either — its idea of
an exit may be the bug.

**The position is then yours.** Nothing is managing its stop-loss until you act,
so close it at the exchange rather than leaving it. Every other stop in the
system — a stale risk gate, the daily loss limit, a revoked mandate — blocks new
entries only and lets exits run. The kill switch is the one that does not, and
that is the whole reason it is a separate instrument.

## Logs

Every process logs structured JSON to stdout, which journald keeps:

```bash
journalctl -u engine-live -f
journalctl -u engine-live -f | jq 'select(.account_id == "acct_1")'
journalctl -u engine-worker@1 --since "1 hour ago"
```

## When something is wrong

`docs/runbook-live.md`. It covers the three different ways to stop an account
and why choosing the wrong one under pressure matters, what `HALTED` means and
how to clear it, why an order was refused, and the one thing worth knowing
before an incident:

> **During a `trading-core` outage, the kill switch is the only way to stop an
> account.** A revocation issued while it cannot reach this service does not
> arrive. That is the accepted cost of trading surviving its control plane
> (ADR-002), and the kill switch depends on neither service.

