from market_arena.sim.book import BUY, SELL, Order, OrderBook


def mk(i, owner, side, px, qty, t=0):
    return Order(i, owner, side, px, qty, t)


def test_rest_and_best_prices():
    b = OrderBook()
    b.limit(mk(1, "a", BUY, 99, 5))
    b.limit(mk(2, "a", SELL, 101, 5))
    assert b.best_bid() == 99 and b.best_ask() == 101
    assert b.mid() == 100 and b.spread() == 2


def test_price_time_priority():
    b = OrderBook()
    b.limit(mk(1, "first", SELL, 101, 3))
    b.limit(mk(2, "second", SELL, 101, 3))
    b.limit(mk(3, "better", SELL, 100, 1))
    fills = b.market("t", BUY, 5)
    assert [(f.maker, f.price, f.qty) for f in fills] == [
        ("better", 100, 1),
        ("first", 101, 3),
        ("second", 101, 1),
    ]
    assert b.depth()[1] == [(101, 2)]


def test_partial_fill_then_rest_remainder():
    b = OrderBook()
    b.limit(mk(1, "m", SELL, 100, 2))
    fills = b.limit(mk(2, "t", BUY, 101, 5))
    assert sum(f.qty for f in fills) == 2 and fills[0].price == 100
    assert b.best_bid() == 101 and b.orders[2].qty == 3
    assert b.best_ask() is None


def test_cancel_removes_liquidity():
    b = OrderBook()
    b.limit(mk(1, "x", SELL, 100, 2))
    b.limit(mk(2, "y", SELL, 100, 2))
    assert b.cancel(1).owner == "x"
    assert b.depth()[1] == [(100, 2)]
    fills = b.market("t", BUY, 3)
    assert [(f.maker, f.qty) for f in fills] == [("y", 2)]
    assert b.best_ask() is None and not b.orders
    assert b.cancel(1) is None


def test_market_sweeps_levels_and_buyer_seller():
    b = OrderBook()
    for i, px in enumerate([98, 99, 97]):
        b.limit(mk(i, f"m{px}", BUY, px, 1))
    fills = b.market("seller", SELL, 2)
    assert [f.price for f in fills] == [99, 98]
    assert fills[0].seller == "seller" and fills[0].buyer == "m99"
    assert b.best_bid() == 97


def test_limit_does_not_cross_through_its_price():
    b = OrderBook()
    b.limit(mk(1, "m", SELL, 100, 1))
    b.limit(mk(2, "m", SELL, 102, 1))
    fills = b.limit(mk(3, "t", BUY, 101, 3))
    assert sum(f.qty for f in fills) == 1
    assert b.best_bid() == 101 and b.best_ask() == 102
