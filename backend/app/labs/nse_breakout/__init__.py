"""NSE Breakout Tracker — daily pre-breakout radar for Indian equities.

Scans every NSE equity daily, records which stocks are approaching a daily
resistance level, confirms when a breakout actually happens, and measures what
followed — so the readiness score can be judged by outcomes rather than by
how sensible it sounds.

**No orders, no wallet, no broker.** It reads two keyless exchange sources and
writes only its own `bt_*` tables.
"""
