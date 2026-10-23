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
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(reply).encode())

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


def _client(srv):
    import fofstudio.llm as llm
    cfg = dict(config.settings()["ollama"], url=f"http://127.0.0.1:{srv.server_address[1]}",
               num_predict=1000, num_ctx=4096, max_predict=8000, max_ctx=16384)
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
