from rbx_boca import interactor_launcher as il


def test_address_space_limit_bytes():
    # bash `ulimit -v 1024000` is in KiB -> bytes
    assert il.address_space_limit() == 1024000 * 1024


def test_watchdog_timeout():
    assert il.watchdog_timeout(7) == (7, 5)  # (term_after_seconds, kill_after_seconds)
