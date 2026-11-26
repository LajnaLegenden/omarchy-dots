import argparse
import importlib
import importlib.util
import json
import sys

from crew import __version__, agents, delivery, messages, replies
from crew.errors import CrewError, NothingDeliveredError, TimeoutError_

FEATURE_MODULES = ("broadcast", "channels", "slots", "office", "bar", "guide")


def main(argv):
    parser = get_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    try:
        return args.func(args) or 0
    except CrewError as error:
        print(f"crew: {error}", file=sys.stderr)
        return error.code
    except KeyboardInterrupt:
        return 130


def get_parser():
    parser = argparse.ArgumentParser(prog="crew", description="Message bus for agents running in herdr-core.")
    parser.add_argument("--version", action="version", version=f"crew {__version__}")
    sub = parser.add_subparsers(metavar="command")

    who = sub.add_parser("who", help="list running agents and what they are doing")
    who.add_argument("--json", action="store_true")
    who.set_defaults(func=run_who)

    status = sub.add_parser("status", help="tell other agents what you are working on")
    status.add_argument("task", nargs="?")
    status.add_argument("--clear", action="store_true")
    status.set_defaults(func=run_status)

    send = sub.add_parser("send", help="message one or more agents")
    send.add_argument("target", help="address, hc name, office/role or all; comma-separate several")
    send.add_argument("text", help="the message; - reads stdin")
    send.add_argument("--reply", action="store_true", help="ask for a reply (crew reply)")
    send.add_argument("--no-reply", dest="reply", action="store_false")
    send.add_argument("--json", action="store_true")
    send.set_defaults(func=run_send)

    reply = sub.add_parser("reply", help="answer a crew message")
    reply.add_argument("message_id")
    reply.add_argument("text", help="the answer; - reads stdin")
    reply.set_defaults(func=run_reply)

    list_replies = sub.add_parser("replies", help="show replies to a message")
    list_replies.add_argument("message_id")
    list_replies.add_argument("--follow", action="store_true")
    list_replies.add_argument("--timeout", type=float, default=600)
    list_replies.add_argument("--json", action="store_true")
    list_replies.set_defaults(func=run_replies)

    for name in FEATURE_MODULES:
        if importlib.util.find_spec(f"crew.{name}") is not None:
            importlib.import_module(f"crew.{name}").add_commands(sub)
    return parser


def run_who(args):
    all_agents = agents.get_agents()
    if args.json:
        print(json.dumps({"agents": all_agents}, ensure_ascii=False))
        return 0
    for agent in all_agents:
        marker = "*" if agent["self"] else " "
        role = f" [{agent['office']}/{agent['role']}]" if agent["office"] else ""
        task = f"  — {agent['task']}" if agent["task"] else ""
        print(f"{marker}{agent['address']:<5} {agent['status']:<8} {agent['agent']:<12} {agent['where']}{role}{task}")
    return 0


def run_status(args):
    if args.clear == (args.task is not None):
        raise CrewError("give a task or --clear")
    address = agents.set_task(None if args.clear else args.task)
    print(f"{address}: {'cleared' if args.clear else args.task}")
    return 0


def run_send(args):
    text = sys.stdin.read().strip() if args.text == "-" else args.text
    refs = [ref for ref in args.target.split(",") if ref]
    targets = agents.get_targets(refs, agents.get_agents())
    result = messages.send_message(text, targets, wants_reply=args.reply)
    print_deliveries(result, args.json)
    if not any(d["status"] == "sent" for d in result["deliveries"]):
        raise NothingDeliveredError("nothing delivered")
    return 0


def print_deliveries(result, as_json):
    if as_json:
        print(json.dumps(result, ensure_ascii=False))
        return
    print(result["id"])
    for record in result["deliveries"]:
        reason = f" ({record['reason']})" if record["reason"] else ""
        print(f"  {record['to']:<5} {record['status']}{reason}")


def run_reply(args):
    text = sys.stdin.read().strip() if args.text == "-" else args.text
    if not text:
        raise CrewError("empty reply")
    record = replies.add_reply(args.message_id, text)
    print(f"replied to {args.message_id} as {record['from']}")
    return 0


def run_replies(args):
    envelope = messages.get_message(args.message_id)
    print_reply = (lambda r: print(json.dumps(r, ensure_ascii=False), flush=True)) if args.json else print_reply_line
    if not args.follow:
        for record in replies.get_replies(args.message_id):
            print_reply(record)
        return 0
    expected = get_sent_addresses(args.message_id) or envelope["to"]
    _, missing = replies.wait_for_replies(args.message_id, expected, args.timeout, on_reply=print_reply)
    if missing:
        print(f"no reply from: {', '.join(missing)}", file=sys.stderr)
        raise TimeoutError_("timed out waiting for replies")
    return 0


def get_sent_addresses(message_id):
    return [d["to"] for d in delivery.get_deliveries(message_id) if d["status"] == "sent"]


def print_reply_line(record):
    print(f"{record['from']:<5} {record.get('where') or '':<28} {record['text']}", flush=True)
