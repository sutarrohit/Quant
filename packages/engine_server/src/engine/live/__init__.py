"""Live trading (spec section 10).

Unblocked by docs/adr-001-live-execution.md, which decides that Nautilus
submits orders directly and nothing else sends a live trade.

**Nothing here trades real money yet.** ADR-001 records seven conditions before
a real key is loaded, and none are met. What exists is the control plane: a
record of what *should* be running, and a loop that makes it so.
"""
