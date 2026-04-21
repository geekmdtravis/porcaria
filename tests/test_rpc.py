from __future__ import annotations

from porcaria.daemon.rpc import Request, Response


def test_request_roundtrip():
    r = Request(method="status", params={"which": "all"})
    r2 = Request.from_json(r.to_json())
    assert r2.method == "status"
    assert r2.params == {"which": "all"}
    assert r2.id == r.id


def test_response_success_and_failure():
    ok = Response.success("abc", {"x": 1})
    assert ok.ok and ok.result == {"x": 1}
    ok2 = Response.from_json(ok.to_json())
    assert ok2.ok and ok2.result == {"x": 1}

    err = Response.failure("abc", "bad", "nope")
    assert not err.ok
    assert err.error == {"code": "bad", "message": "nope"}
    err2 = Response.from_json(err.to_json())
    assert not err2.ok and err2.error == {"code": "bad", "message": "nope"}
