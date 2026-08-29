from eval_harness import Harness, Task, contains, exact


def test_pass_fail_report() -> None:
    h = Harness(
        [
            Task("t1", "2+2", "4", exact),
            Task("t2", "hello", "world", contains),
        ]
    )
    results = h.run(lambda p: "4" if p == "2+2" else "hello there")
    assert results[0].ok is True
    assert results[1].ok is False
    assert h.score(results) == 0.5
    md = h.report(results)
    assert "Passed 1/2" in md
    assert "FAIL" in md


def test_empty_rejected() -> None:
    try:
        Harness([])
        raise AssertionError("expected")
    except ValueError:
        pass
