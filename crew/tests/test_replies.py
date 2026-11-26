import threading
import time

from conftest import agent

from crew import store


def send(crew, *targets):
    _, out, _ = crew.run_json("send", ",".join(targets), "--reply", "status?")
    return out["id"]


def test_reply_is_recorded_with_sender_identity(crew):
    crew.set_terminals([agent("t7", where="🎬 mediatool / 1")])
    message_id = send(crew, "t7")
    crew.be("t7")
    crew.run("reply", message_id, "on it")
    [record] = store.get_records(crew.state_dir / "replies" / f"{message_id}.jsonl")
    assert (record["from"], record["where"], record["text"]) == ("t7", "🎬 mediatool / 1", "on it")


def test_unknown_message_exits_3(crew):
    code, _, _ = crew.run("reply", "m-nope", "x")
    assert code == 3


def test_reply_to_agent_sender_is_pushed_back(crew):
    crew.set_terminals([agent("t7"), agent("t8")])
    crew.be("t8")
    message_id = send(crew, "t7")
    crew.be("t7")
    crew.run("reply", message_id, "done")
    pushed = [c for c in crew.calls("send") if c[1] == "t8"]
    assert len(pushed) == 1 and f'reply-to="{message_id}"' in pushed[0][2]


def test_reply_to_human_is_not_pushed(crew):
    crew.set_terminals([agent("t7")])
    message_id = send(crew, "t7")
    crew.be("t7")
    crew.run("reply", message_id, "done")
    assert len(crew.calls("send")) == 1


def test_follow_ends_when_all_replied(crew):
    crew.set_terminals([agent("t7"), agent("t8")])
    message_id = send(crew, "t7", "t8")
    path = crew.state_dir / "replies" / f"{message_id}.jsonl"

    def reply_later():
        for address in ("t7", "t8"):
            time.sleep(0.2)
            store.append_record(path, {"id": f"r-{address}", "msg": message_id, "from": address, "text": "ok"})

    threading.Thread(target=reply_later).start()
    code, out, _ = crew.run("replies", message_id, "--follow", "--timeout", "5")
    assert code == 0 and out.count("ok") == 2


def test_follow_times_out_listing_missing(crew):
    crew.set_terminals([agent("t7")])
    message_id = send(crew, "t7")
    code, _, err = crew.run("replies", message_id, "--follow", "--timeout", "0.5")
    assert code == 5 and "t7" in err


def test_partial_last_line_is_ignored(crew):
    path = crew.state_dir / "replies" / "m-x.jsonl"
    store.append_record(path, {"id": "r-1", "text": "ok"})
    with open(path, "a") as file:
        file.write('{"id": "r-2", "te')
    assert [r["id"] for r in store.get_records(path)] == ["r-1"]


def test_line_separator_in_text_survives_the_log(crew):
    path = crew.state_dir / "replies" / "m-x.jsonl"
    store.append_record(path, {"id": "r-1", "text": "ok saved"})
    assert store.get_records(path)[0]["text"] == "ok saved"


def test_long_reply_goes_to_a_file(crew):
    crew.set_terminals([agent("t7")])
    message_id = send(crew, "t7")
    crew.be("t7")
    code, _, _ = crew.run("reply", message_id, "x" * 20000)
    [record] = store.get_records(crew.state_dir / "replies" / f"{message_id}.jsonl")
    assert code == 0 and record["text"].startswith("(long reply")
