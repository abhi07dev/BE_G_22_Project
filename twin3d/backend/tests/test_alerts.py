from app.alerts import AlertEngine, Zone, point_in_polygon

SQUARE = [[0, 0], [10, 0], [10, 10], [0, 10]]


def test_point_in_polygon():
    assert point_in_polygon(5, 5, SQUARE)
    assert not point_in_polygon(11, 5, SQUARE)


def test_zone_enter_with_cooldown():
    eng = AlertEngine([Zone(1, "Vault", "restricted", SQUARE)], cooldown=60)
    assert len(eng.evaluate([(7, 5, 5)], now=1000)) == 1
    assert eng.evaluate([(7, 5, 5)], now=1030) == []
    assert len(eng.evaluate([(7, 5, 5)], now=1061)) == 1


def test_outside_restricted_zone_is_quiet():
    eng = AlertEngine([Zone(1, "Vault", "restricted", SQUARE)])
    assert eng.evaluate([(7, 20, 20)], now=1) == []


def test_occupancy_limit():
    eng = AlertEngine([Zone(2, "Lobby", "monitored", SQUARE, max_occupancy=2)])
    people = [(i, 1 + i, 1) for i in range(3)]
    out = eng.evaluate(people, now=1)
    assert out and out[0]["type"] == "occupancy_exceeded" and out[0]["count"] == 3
