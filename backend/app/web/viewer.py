"""Read-only web browser for the prajna database.

There is no psql or pgAdmin on this host, so this is the visual surface.

Two safety properties, both structural rather than advisory:
  * every query runs inside SET TRANSACTION READ ONLY, so Postgres itself
    rejects a write — not a regex we hoped was complete;
  * it binds to 127.0.0.1 only. It holds database credentials and must not be
    reachable from the network.

It also inherits app.db.engine, so it cannot be pointed at autotrade_pro.
"""

from __future__ import annotations

import html
from decimal import Decimal

from fastapi import FastAPI, Form, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from app.core.config import database_name, get_settings
from app.db.engine import get_engine

app = FastAPI(title="prajna db viewer", docs_url=None, redoc_url=None)

CSS = """
:root{--bg:#fbfbfa;--fg:#1a1a18;--mut:#6b6b66;--line:#e2e1dd;--acc:#1f6feb;
      --card:#fff;--warn:#8a5a00;--warnbg:#fff8e6}
@media(prefers-color-scheme:dark){:root{--bg:#16161a;--fg:#e8e8e3;--mut:#9a9a94;
      --line:#2e2e34;--acc:#6aa9ff;--card:#1d1d22;--warn:#e0b050;--warnbg:#2a2415}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
     font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
header{padding:12px 18px;border-bottom:1px solid var(--line);display:flex;
       gap:16px;align-items:baseline;flex-wrap:wrap;background:var(--card)}
header b{font-size:15px}header span{color:var(--mut);font-size:12px}
.wrap{display:flex;min-height:calc(100vh - 53px);flex-wrap:wrap}
nav{width:290px;min-width:240px;border-right:1px solid var(--line);
    padding:14px 0;background:var(--card)}
nav a{display:flex;justify-content:space-between;gap:10px;padding:5px 18px;
      color:var(--fg);text-decoration:none}
nav a:hover{background:var(--bg)}nav a.on{border-left:3px solid var(--acc);
      padding-left:15px;font-weight:600}
nav .n{color:var(--mut)}
nav h4{margin:14px 18px 6px;color:var(--mut);font-size:11px;letter-spacing:.09em;
       text-transform:uppercase;font-weight:600}
main{flex:1;padding:18px;min-width:0}
h2{margin:0 0 12px;font-size:15px}
form{margin:0 0 16px}
textarea{width:100%;min-height:92px;background:var(--card);color:var(--fg);
   border:1px solid var(--line);border-radius:6px;padding:10px;font:inherit;resize:vertical}
button{margin-top:8px;background:var(--acc);color:#fff;border:0;border-radius:6px;
   padding:7px 16px;font:inherit;cursor:pointer}
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:6px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{padding:6px 10px;text-align:left;border-bottom:1px solid var(--line);
      white-space:nowrap;vertical-align:top}
th{background:var(--bg);font-weight:600;position:sticky;top:0}
tr:last-child td{border-bottom:0}
td.nul{color:var(--mut);font-style:italic}
.err{background:var(--warnbg);color:var(--warn);border:1px solid var(--warn);
     border-radius:6px;padding:10px;white-space:pre-wrap}
.note{color:var(--mut);margin:10px 0}
.ro{background:var(--warnbg);color:var(--warn);padding:2px 8px;border-radius:99px;
    font-size:11px;font-weight:600}
"""


def _cell(v) -> str:
    if v is None:
        return '<td class="nul">null</td>'
    if isinstance(v, Decimal):
        v = f"{v:g}"
    s = str(v)
    if len(s) > 90:
        s = s[:87] + "…"
    return f"<td>{html.escape(s)}</td>"


async def _tables(conn):
    rows = (await conn.execute(text("""
        select c.relname, coalesce(s.n_live_tup,0)
        from pg_class c
        join pg_namespace n on n.oid=c.relnamespace
        left join pg_stat_user_tables s on s.relid=c.oid
        where c.relkind='r' and n.nspname='public'
        order by c.relname
    """))).all()
    return [(r[0], r[1]) for r in rows]


GROUPS = {
    "control plane": {"ingest_run", "raw_payload", "ingest_watermark", "ingest_anomaly",
                      "alembic_version"},
    "contracts": {"trading_session", "instrument", "instrument_universe_membership"},
    "pre-open": {"preopen_tick", "preopen_book", "preopen_session_status"},
    "market data": {"ohlcv_bar", "tick_archive"},
    "reference": {"corporate_action", "fundamental_snapshot", "macro_observation",
                  "news_article"},
}


def _shell(db: str, tables, active: str, body: str) -> str:
    nav = []
    seen = set()
    for label, members in GROUPS.items():
        items = [(t, n) for t, n in tables if t in members]
        if not items:
            continue
        nav.append(f"<h4>{label}</h4>")
        for t, n in items:
            seen.add(t)
            on = " class='on'" if t == active else ""
            nav.append(f"<a href='/t/{t}'{on}><span>{t}</span><span class='n'>{n:,}</span></a>")
    other = [(t, n) for t, n in tables if t not in seen]
    if other:
        nav.append("<h4>other</h4>")
        for t, n in other:
            on = " class='on'" if t == active else ""
            nav.append(f"<a href='/t/{t}'{on}><span>{t}</span><span class='n'>{n:,}</span></a>")
    return f"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>prajna · {html.escape(db)}</title><style>{CSS}</style>
<header><b>prajna</b><span>database: {html.escape(db)}</span>
<span class=ro>READ ONLY</span>
<span style="margin-left:auto"><a href="/" style="color:var(--acc)">sql</a></span></header>
<div class=wrap><nav>{''.join(nav)}</nav><main>{body}</main></div>"""


@app.get("/", response_class=HTMLResponse)
async def home(q: str = Query("")):
    eng = get_engine()
    async with eng.connect() as c:
        await c.execute(text("SET TRANSACTION READ ONLY"))
        db = (await c.execute(text("select current_database()"))).scalar()
        tables = await _tables(c)
        body = [
            "<h2>Query</h2>",
            '<form method=get><textarea name=q placeholder="select * from ingest_run '
            'order by started_at desc limit 50">' + html.escape(q) + "</textarea>"
            "<button>Run</button></form>",
            '<p class=note>Runs inside <code>SET TRANSACTION READ ONLY</code> — '
            "Postgres rejects any write.</p>",
        ]
        if q.strip():
            body.append(await _run(c, q))
        else:
            body.append(
                "<h2>Tables</h2><div class=tw><table><tr><th>table</th><th>rows</th></tr>"
                + "".join(f"<tr><td><a href='/t/{t}' style='color:var(--acc)'>{t}</a></td>"
                          f"<td>{n:,}</td></tr>" for t, n in tables)
                + "</table></div>"
            )
    return HTMLResponse(_shell(db, tables, "", "".join(body)))


async def _run(conn, sql: str) -> str:
    try:
        res = await conn.execute(text(sql))
    except Exception as e:
        return f"<div class=err>{html.escape(type(e).__name__)}: " \
               f"{html.escape(str(e).splitlines()[0])}</div>"
    if not res.returns_rows:
        return "<p class=note>Statement returned no rows.</p>"
    rows = res.fetchmany(500)
    cols = list(res.keys())
    head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(_cell(v) for v in r) + "</tr>" for r in rows)
    return (f"<div class=tw><table><tr>{head}</tr>{body}</table></div>"
            f"<p class=note>{len(rows)} row(s)"
            f"{' — truncated at 500' if len(rows) == 500 else ''}</p>")


@app.get("/t/{table}", response_class=HTMLResponse)
async def browse(table: str, limit: int = 100):
    eng = get_engine()
    async with eng.connect() as c:
        await c.execute(text("SET TRANSACTION READ ONLY"))
        db = (await c.execute(text("select current_database()"))).scalar()
        tables = await _tables(c)
        if table not in {t for t, _ in tables}:
            return HTMLResponse(_shell(db, tables, "", "<div class=err>no such table</div>"), 404)

        cols = (await c.execute(text("""
            select column_name, data_type, is_nullable
            from information_schema.columns
            where table_schema='public' and table_name=:t order by ordinal_position
        """), {"t": table})).all()
        schema = "".join(
            f"<tr><td>{html.escape(a)}</td><td>{html.escape(b)}</td>"
            f"<td>{'null' if d == 'YES' else 'not null'}</td></tr>" for a, b, d in cols
        )
        cons = (await c.execute(text("""
            select conname, pg_get_constraintdef(oid)
            from pg_constraint where conrelid = to_regclass(:t) order by conname
        """), {"t": f"public.{table}"})).all()
        clist = "".join(
            f"<tr><td>{html.escape(n)}</td><td>{html.escape(d)}</td></tr>" for n, d in cons
        )
        # table is whitelisted against pg_tables above, so interpolation is safe here
        data = await _run(c, f'select * from "{table}" limit {int(limit)}')

    body = (
        f"<h2>{html.escape(table)}</h2>{data}"
        f"<h2 style='margin-top:22px'>Columns</h2><div class=tw><table>"
        f"<tr><th>column</th><th>type</th><th>null</th></tr>{schema}</table></div>"
        f"<h2 style='margin-top:22px'>Constraints</h2><div class=tw><table>"
        f"<tr><th>name</th><th>definition</th></tr>{clist}</table></div>"
    )
    return HTMLResponse(_shell(db, tables, table, body))


def serve(host: str = "127.0.0.1", port: int = 8081) -> None:
    import uvicorn
    s = get_settings()
    print(f"prajna db viewer → http://{host}:{port}   "
          f"(database: {database_name(s.PRAJNA_DATABASE_URL)}, READ ONLY)")
    uvicorn.run(app, host=host, port=port, log_level="warning")
