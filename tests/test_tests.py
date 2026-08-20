from hound_agent.ingest.tests import parse_failed_tests
from tests.conftest import fixture


def test_failed_line_parse():
    tests = parse_failed_tests(fixture("pytest_fail.log"))
    assert len(tests) == 1
    t = tests[0]
    assert t.name == "tests/test_cart.py::test_cart_total"
    assert t.file == "tests/test_cart.py"
    assert "assert 5.0 == 10.0" in t.assertion


def test_header_parse():
    text = "___________ test_from_header ___________\nstuff"
    tests = parse_failed_tests(text)
    assert any(t.name == "test_from_header" for t in tests)


def test_dedup_names():
    text = "FAILED a.py::t - x\nFAILED a.py::t - x\n"
    assert len(parse_failed_tests(text)) == 1


def test_no_tests():
    assert parse_failed_tests("all passed\n") == []
