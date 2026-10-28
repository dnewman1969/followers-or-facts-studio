"""The local AI's answer size grows by itself when an answer runs out of room."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from fofstudio import config
from fofstudio.util import StageError


def _server(answers):
    seen = []

    class Fake(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body["options"])
            reply = answers[min(len(seen) - 1, len(answers) - 1)]
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            for part in reply if isinstance(reply, list) else [reply]:   # a list = streamed pieces
                self.wfile.write(json.dumps(part).encode() + b"\n")

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


def _client(srv):
    import fofstudio.llm as llm
    cfg = dict(config.settings()["ollama"], url=f"http://127.0.0.1:{srv.server_address[1]}",
               num_predict=1000, num_ctx=4096, max_predict=8000, max_ctx=16384, format_check=False)
    return llm.Ollama(cfg)


def test_runs_out_of_room_then_gets_more(data):
    short = {"message": {"content": '{"shots": [{"idea": "a'}, "done": True, "done_reason": "length",
             "prompt_eval_count": 3500, "eval_count": 1000}
    good = {"message": {"content": '{"shots": []}'}, "done": True, "done_reason": "stop"}
    srv, seen = _server([short, good])
    out = _real_chat_json(_client(srv))
    srv.shutdown()
    assert out == {"shots": []}
    assert seen[1]["num_predict"] == 2000 and seen[1]["num_ctx"] >= 3500 + 2000
    assert seen[1]["presence_penalty"] > seen[0]["presence_penalty"]


def _real_chat_json(client):
    import fofstudio.llm as llm
    return llm.Ollama.chat_json(client, [{"role": "user", "content": "x"}], {"type": "object"})


def test_gives_up_with_a_clear_message(data):
    short = {"message": {"content": "{"}, "done": True, "done_reason": "length", "prompt_eval_count": 100}
    srv, seen = _server([short])
    with pytest.raises(StageError, match="kept running out of room"):
        _real_chat_json(_client(srv))
    srv.shutdown()
    assert seen[-1]["num_predict"] == 8000   # it tried up to the limit


def test_stuck_answer_is_stopped_and_tried_again(data):
    """Dave's storyboard sat at '29 words written' until it ran out of room: the AI was writing blank space."""
    stuck = [{"message": {"content": '{"shots": ['}, "done": False}] + \
            [{"message": {"content": "\n"}, "done": False} for _ in range(400)]
    good = {"message": {"content": '{"shots": []}'}, "done": True, "done_reason": "stop"}
    srv, seen = _server([stuck, good])
    client = _client(srv)
    out = _real_chat_json(client)
    srv.shutdown()
    assert out == {"shots": []} and len(seen) == 2
    assert seen[1]["temperature"] > seen[0]["temperature"] and "stuck" in client.retries[0]


def test_a_thinking_model_is_not_mistaken_for_a_stuck_one(data):
    """Dave's caricature research: qwen3-vl streamed its reasoning as 'thinking' with empty content, and the
    Studio called that 'stuck writing blank space' and gave up on every photo."""
    import fofstudio.llm as llm
    thinking = [{"message": {"content": "", "thinking": "Looking at the face. "}, "done": False}
                for _ in range(400)]
    answer = thinking + [{"message": {"content": '{"is_portrait": true}'}, "done": True, "done_reason": "stop"}]
    srv, seen = _server([answer])
    client = _client(srv)
    out = llm.Ollama.chat(client, [{"role": "user", "content": "x", "images": ["abc"]}])
    srv.shutdown()
    assert out == '{"is_portrait": true}' and len(seen) == 1 and not client.retries
    only = [{"message": {"content": "", "thinking": 'The answer: {"is_portrait": true, "nose": "long"}'},
             "done": True, "done_reason": "stop"}]
    srv, seen = _server([only])
    out = llm.Ollama.chat(_client(srv), [{"role": "user", "content": "x"}])
    srv.shutdown()
    assert '"nose": "long"' in out          # an answer left only in its thinking is still used


# ---------------------------------------------------------------- v0.5.5: answer formats and models per job
def test_schema_problems_catch_what_ollama_let_through():
    import fofstudio.llm as llm
    schema = {"type": "object", "required": ["scenes", "title"], "properties": {
        "title": {"type": "string"},
        "scenes": {"type": "array", "minItems": 16, "items": {"type": "object", "required": ["role"], "properties": {
            "role": {"type": "string", "enum": ["intro", "claim"]}, "n": {"type": "integer", "maximum": 5}}}}}}
    bad = {"scenes": [{"role": "outro", "n": 9}, {}]}
    probs = llm.schema_problems(bad, schema)
    assert any('missing "title"' in p for p in probs)
    assert any("needs at least 16" in p for p in probs)
    assert any("'outro'" in p for p in probs) and any("above 5" in p for p in probs)
    assert any('missing "role"' in p for p in probs)
    assert llm.schema_problems({"title": "x", "scenes": [{"role": "intro"}] * 16}, schema) == []
    assert llm.strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def _paths_server(by_path):
    """A fake Ollama that answers differently on /api/chat and /api/generate, and says its version."""
    seen = []

    class Fake(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"version": "0.30.7"}')

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, body))
            answers = by_path[self.path]
            reply = answers.pop(0) if len(answers) > 1 else answers[0]
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            key = "message" if self.path == "/api/chat" else "response"
            part = {key: {"content": reply} if key == "message" else reply, "done": True, "done_reason": "stop"}
            self.wfile.write(json.dumps(part).encode() + b"\n")

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


def test_ollama_that_ignores_the_format_on_chat_is_routed_to_generate(data):
    """Ollama issue #14645: with thinking off, /api/chat ignored the schema (3 scenes for 16)."""
    import fofstudio.llm as llm
    llm.forget_format_checks()
    srv, seen = _paths_server({
        "/api/chat": ['{"colors": ["purple", "orange"]}'],                       # schema ignored
        "/api/generate": ['{"colors": ["red", "green", "blue", "red"]}', '{"ok": ["a", "b"]}']})
    cfg = dict(config.settings()["ollama"], url=f"http://127.0.0.1:{srv.server_address[1]}")
    client = llm.Ollama(cfg)
    out = client.chat_json([{"role": "system", "content": "rules"}, {"role": "user", "content": "go"}],
                           {"type": "object", "properties": {"ok": {"type": "array", "minItems": 2}}, "required": ["ok"]})
    srv.shutdown()
    assert out == {"ok": ["a", "b"]}
    assert [p for p, _ in seen] == ["/api/chat", "/api/generate", "/api/generate"]
    last = seen[-1][1]
    assert last["system"] == "rules" and last["prompt"] == "go" and "format" in last
    saved = json.loads((config.data_dir() / "logs" / "ollama-format-check.json").read_text())
    assert saved[f"{cfg['writer_model']}@0.30.7"]["route"] == "generate"


def test_answers_that_break_the_format_are_sent_back(data):
    import fofstudio.llm as llm
    schema = {"type": "object", "properties": {"scenes": {"type": "array", "minItems": 3}}, "required": ["scenes"]}
    short = {"message": {"content": '{"scenes": [1]}'}, "done": True, "done_reason": "stop"}
    good = {"message": {"content": '```json\n{"scenes": [1, 2, 3]}\n```'}, "done": True, "done_reason": "stop"}
    srv, seen = _server([short, good])
    client = _client(srv)
    assert client.chat_json([{"role": "user", "content": "x"}], schema) == {"scenes": [1, 2, 3]}
    assert len(seen) == 2 and "broke its format" in client.retries[0]
    srv.shutdown()
    srv, seen = _server([short])
    client = _client(srv)
    with pytest.raises(StageError, match="wrong format"):
        client.chat_json([{"role": "user", "content": "x"}], schema)
    assert len(seen) == 1 + llm.FORMAT_RETRIES
    assert client.chat_json([{"role": "user", "content": "x"}], schema, lenient=True) == {"scenes": [1]}
    srv.shutdown()


def test_each_job_can_have_its_own_model(data):
    import fofstudio.llm as llm
    cfg = config.settings()
    cfg["models"]["script_write"] = "gemma4:12b"
    try:
        assert llm.model_for("script_write") == "gemma4:12b"
        assert llm.model_for("research_plan") == cfg["ollama"]["writer_model"]
        assert llm.model_for("checks") == cfg["ollama"]["checker_model"]
        assert llm.Ollama(job="script_write").model == "gemma4:12b"
    finally:
        cfg["models"]["script_write"] = ""
