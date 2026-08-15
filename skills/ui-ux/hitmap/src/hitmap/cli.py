from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__
from .cdp import CDPClient, CDPError, evaluate, find_browser, launch_browser, new_page
from .core import summarize
from .probe import PROBE_JS


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hitmap", description="Find visible controls whose interior points are not pointer-reachable in a real Chromium browser.")
    p.add_argument("--version", action="version", version=f"hitmap {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="report whether a Chromium-family browser is available")
    doctor.add_argument("--browser")
    scan = sub.add_parser("scan", help="scan one rendered page state")
    scan.add_argument("url")
    scan.add_argument("--browser")
    scan.add_argument("--json", action="store_true", dest="as_json")
    scan.add_argument("--settle-ms", type=int, default=500)
    scan.add_argument("--width", type=int, default=1280)
    scan.add_argument("--height", type=int, default=720)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        browser = find_browser(args.browser)
        if not browser:
            print("ORACLE_UNAVAILABLE: no Chromium/Chrome executable found", file=sys.stderr)
            return 2
        print(json.dumps({"oracle": "chromium", "browser": browser, "status": "available"}))
        return 0

    browser = find_browser(args.browser)
    if not browser:
        print("ORACLE_UNAVAILABLE: no Chromium/Chrome executable found", file=sys.stderr)
        return 2
    proc = None
    client = None
    try:
        proc = launch_browser(browser)
        ws = new_page(proc.devtools_base, args.url)
        client = CDPClient(ws)
        client.call("Runtime.enable")
        client.call("Page.enable")
        client.call("Emulation.setDeviceMetricsOverride", {"width": args.width, "height": args.height, "deviceScaleFactor": 1, "mobile": False})
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            ready = evaluate(client, "document.readyState")
            href = evaluate(client, "location.href")
            if isinstance(href, str) and href.startswith("chrome-error://"):
                raise CDPError(f"browser refused or failed to load {args.url}")
            if ready == "complete":
                break
            time.sleep(0.05)
        else:
            raise CDPError("page did not reach readyState=complete within 20 seconds")
        time.sleep(max(0, args.settle_ms) / 1000)
        probes = evaluate(client, PROBE_JS)
        if not isinstance(probes, list):
            raise CDPError("probe did not return a target list")
        report = summarize(probes)
        report["url"] = args.url
        report["oracle"] = "chromium"
        if args.as_json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(f"verdict   {report['verdict']}")
            print(f"targets   {report['targets']}")
            print(f"findings  {len(report['findings'])}")
            for item in report["findings"]:
                print(f"  {item['id']}  {item['selector']}  blocked by {', '.join(item['occluders'])}")
        return 3 if report["findings"] else 0
    except (CDPError, OSError, ValueError) as exc:
        print(f"ORACLE_ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if client:
            client.close()
        if proc:
            proc.close()
