from jarvis.hud.page import read_page


def test_should_not_look_up_inherited_state_names_when_state_is_constructor() -> None:
    text = read_page()
    guard = "Object.hasOwn(LOOKS, ev.state)"
    lookup = "LOOKS[ev.state]"
    assert guard in text
    assert lookup in text
    assert text.index(guard) < text.index(lookup)


def test_should_not_reset_backoff_when_http_response_fails() -> None:
    text = read_page()
    start = text.index("async function connect()")
    connect = text[start:]
    guard = "if (!res.ok)"
    reset = "delay = 500;"
    assert guard in connect
    assert reset in connect
    assert connect.index(guard) < connect.index(reset)
    assert "throw" in connect[connect.index(guard) :]


def test_should_stop_forever_when_status_is_401_or_403() -> None:
    text = read_page()
    start = text.index("async function connect()")
    connect = text[start:]
    ok_guard = "if (!res.ok)"
    assert "res.status === 401" in connect
    assert "res.status === 403" in connect
    assert connect.index("res.status === 401") < connect.index(ok_guard)
    assert connect.index("res.status === 403") < connect.index(ok_guard)
