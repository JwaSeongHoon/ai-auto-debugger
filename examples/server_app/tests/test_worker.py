from worker import process


def test_process_average():
    assert process({"id": 1, "total": 10, "count": 2}) == 5
