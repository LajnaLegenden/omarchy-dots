import json

from conftest import agent

from crew import store


def get_posts(crew, channel="general"):
    return store.get_records(crew.state_dir / "channels" / f"{channel}.jsonl")


def read_texts(crew, *args):
    _, out, _ = crew.run("read", "general", "--json", *args)
    return [json.loads(line)["text"] for line in out.splitlines()]


def test_post_without_mentions_is_logged_only(crew):
    crew.set_terminals([agent("t7")])
    code, _, _ = crew.run("post", "general", "build is green")
    assert (code, crew.calls("send")) == (0, [])
    assert get_posts(crew)[0]["text"] == "build is green"


def test_mentions_by_address_and_name_get_the_channel_post(crew):
    crew.set_terminals([agent("t7"), agent("t8", name="review")])
    crew.run("post", "general", "@t7 and @review: look at x.rs")
    sends = crew.calls("send")
    assert sorted(address for _, address, _ in sends) == ["t7", "t8"]
    assert all('post="crew post general' in wire for _, _, wire in sends)


def test_hash_prefix_names_the_same_channel(crew):
    crew.run("post", "#general", "hi")
    assert [post["channel"] for post in get_posts(crew)] == ["general"]


def test_you_mention_is_recorded_not_delivered(crew):
    crew.set_terminals([agent("t7")])
    crew.be("t7")
    crew.run("post", "general", "@you done, please review")
    assert (get_posts(crew)[0]["mentions"], crew.calls("send")) == (["you"], [])


def test_unresolved_mention_is_kept_and_exits_0(crew):
    code, _, err = crew.run("post", "general", "@ghost hello")
    assert (code, get_posts(crew)[0]["unresolved"]) == (0, ["ghost"])
    assert "@ghost" in err


def test_read_since_post_id_returns_later_posts(crew):
    for text in ("one", "two", "three"):
        crew.run("post", "general", text)
    assert read_texts(crew, "--since", get_posts(crew)[0]["id"]) == ["two", "three"]


def test_read_limit_keeps_the_newest(crew):
    for text in ("one", "two", "three"):
        crew.run("post", "general", text)
    assert read_texts(crew, "--limit", "1") == ["three"]


def test_read_missing_channel_is_empty(crew):
    code, out, _ = crew.run("read", "nothing-here")
    assert (code, out) == (0, "")


def test_invalid_channel_name_exits_2(crew):
    code, _, _ = crew.run("post", "Bad Name!", "x")
    assert code == 2
