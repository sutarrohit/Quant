"""Proof the vendored engine resolves, is the expected pinned version, and a stock v2
live node constructs from it (FOUND-01, D-04).

The engine is consumed as a git submodule pinned to an exact upstream commit
(`vendor/nautilus_trader` @ `4692bac35bb11a25eeebb8d7af4d51c55afe53ec`, corrected pin — see
01-03-SUMMARY.md for why the plan's original pin was rejected), installed editable, never as a
published wheel. A silently re-resolved dependency should fail here rather than surfacing as a
mysterious behaviour change three plans later.

`test_live_node_builder_constructs` proves more than importability: it builds the smallest v2
live node the builder accepts — no data clients, no execution clients, no credentials, no
network — and asserts the returned object is a real node instance. It deliberately does not
start the node or drive its event loop; node *startup* against live infrastructure is Phase 5
(PAPER-01) scope, not Phase 1.
"""

import nautilus_trader
from nautilus_trader.common import Environment
from nautilus_trader.live import LiveNode
from nautilus_trader.model import TraderId


def test_engine_version_is_pinned():
    assert nautilus_trader.__version__ == "2.0.0rc4"


def test_live_node_builder_constructs():
    node = LiveNode.builder("ENGINE-IMPORT-TEST", TraderId("TESTER-001"), Environment.SANDBOX).build()
    assert isinstance(node, LiveNode)
