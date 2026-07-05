import argparse
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

import report
from analyzer import QuotaExhaustedError, analyze_site, make_client, synthesize
from scraper import ScrapeError, scrape_site


def read_urls(path: str) -> list[str]:
    p = Path(path)
    if not p.is_file():
        sys.exit(f"Error: URL list '{path}' not found")
    urls = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    if not urls:
        sys.exit(f"Error: no URLs in '{path}'")
    return urls


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape competitors into a comparison + market gap.")
    parser.add_argument("--urls", default="demo_urls.txt", help="file with one competitor URL per line")
    parser.add_argument("--output-dir", default="output", help="where to write the report and Excel")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between sites (be polite)")
    args = parser.parse_args()

    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    load_dotenv()
    client = make_client()
    urls = read_urls(args.urls)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    profiles, failed = [], []
    for i, url in enumerate(urls):
        print(f"[{i + 1}/{len(urls)}] {url}")
        try:
            site = scrape_site(url)
            print(f"    scraped {len(site['text'])} chars from {len(site['pages'])} page(s)")
            profile = analyze_site(client, url, site["text"])
            print(f"    → {profile.name}: {profile.usp[:70]}...")
            profiles.append(profile)
        except ScrapeError as err:
            failed.append(url)
            print(f"    [SKIP] {err}")
        except QuotaExhaustedError as err:
            print(f"\n[STOP] {err}")
            print(f"Analyzed {len(profiles)} site(s) before the quota ran out.")
            break
        except Exception as err:
            failed.append(url)
            print(f"    [ERROR] {err}")
        if args.delay and i < len(urls) - 1:
            time.sleep(args.delay)

    if len(profiles) < 2:
        sys.exit("\nNeed at least 2 analyzed competitors to build a comparison.")

    print("\nSynthesizing market analysis...")
    try:
        insight = synthesize(client, profiles)
    except QuotaExhaustedError as err:
        print(f"[WARN] {err}\nWriting the comparison without the market-gap analysis.")
        from analyzer import MarketInsight

        insight = MarketInsight()

    md = report.build_markdown(profiles, insight)
    md_path = out_dir / "competitor_snapshot.md"
    xlsx_path = out_dir / "competitor_snapshot.xlsx"
    md_path.write_text(md, encoding="utf-8")
    report.write_excel(profiles, insight, xlsx_path)

    print("\n" + md)
    print(f"\nWritten:\n  {md_path}\n  {xlsx_path}")
    if failed:
        print(f"Skipped {len(failed)}: {', '.join(failed)}")


if __name__ == "__main__":
    main()
