"""webgrab command line: list | probe | fetch | record.

`probe` is the point of the whole thing: it turns every 'this endpoint works'
claim in the registry from prose into something a command re-verifies. It exits
non-zero when any source fails, so it can gate a build.
"""
import argparse
import pathlib
import sys

from . import http, probe, registry


def _params(pairs):
    out = {}
    for p in pairs or []:
        if "=" not in p:
            sys.exit(f"--param expects key=value, got {p!r}")
        k, _, v = p.partition("=")
        out[k] = v
    return out


def cmd_list(args):
    reg = registry.load(args.registry)
    width = max(len(k) for k in reg)
    order = {"works": 0, "unconfirmed": 1, "needs-browser": 2, "needs-login": 3,
             "dead": 4, "blocked": 5, "licensed": 6}
    for e in sorted(reg.values(), key=lambda e: (order.get(e.status, 9), e.id)):
        verified = e.last_verified.isoformat() if e.last_verified else "never"
        print(f"{e.id:<{width}}  {e.status:<14} verified={verified:<11} "
              f"ua={e.user_agent:<8} retries={e.retries}")
    return 0


def cmd_probe(args):
    reg = registry.load(args.registry)
    results = probe.run(reg)
    width = max((len(v.id) for v in results), default=10)
    bad = 0
    skipped = 0
    for v in results:
        if v.detail.startswith("SKIPPED"):
            mark, skipped = "SKIP", skipped + 1
        elif v.ok:
            mark = " ok "
        else:
            mark, bad = "FAIL", bad + 1
        print(f"[{mark}] {v.id:<{width}}  {v.detail}")

    total = len(results)
    print(f"\nprobed {total - skipped} of {total} working sources; "
          f"{bad} failed, {skipped} skipped for want of probe params.")
    if skipped:
        print("A skipped source is UNVERIFIED, not passing.")
    return 1 if bad else 0


def cmd_fetch(args):
    reg = registry.load(args.registry)
    if args.id not in reg:
        sys.exit(f"unknown source {args.id!r}; try `webgrab list`")
    e = reg[args.id]
    if e.status != "works":
        sys.exit(f"{e.id} is marked '{e.status}', not 'works'. Registry says:\n{e.notes.strip()}")
    text = http.get(e.resolve(**_params(args.param)), ua=e.user_agent, retries=e.retries)
    sys.stdout.write(text)
    return 0


def cmd_record(args):
    """Refresh a fixture from the live site. Fixtures are evidence, so this is
    the only sanctioned way they change -- never hand-edited."""
    reg = registry.load(args.registry)
    if args.id not in reg:
        sys.exit(f"unknown source {args.id!r}")
    e = reg[args.id]
    params = _params(args.param) or (e.probe or {})
    text = http.get(e.resolve(**params), ua=e.user_agent, retries=e.retries)
    dest = pathlib.Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)
    print(f"recorded {len(text)} bytes from {e.id} -> {dest}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="webgrab", description=__doc__.splitlines()[0])
    ap.add_argument("--registry", default=None, help="path to sources.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="show every source and its status").set_defaults(fn=cmd_list)
    sub.add_parser("probe", help="re-verify every working source; non-zero on failure"
                   ).set_defaults(fn=cmd_probe)

    f = sub.add_parser("fetch", help="fetch one source to stdout")
    f.add_argument("id"); f.add_argument("--param", action="append")
    f.set_defaults(fn=cmd_fetch)

    r = sub.add_parser("record", help="refresh a fixture from the live site")
    r.add_argument("id"); r.add_argument("--out", required=True)
    r.add_argument("--param", action="append")
    r.set_defaults(fn=cmd_record)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
