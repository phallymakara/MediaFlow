#!/usr/bin/env python3
"""CLI Drama Catalog Explorer: Fetch, view, and inspect short dramas across platforms.

Usage:
  # View all dramas from TikTok, DramaBox, and ReelShort:
  uv run python tools/drama_catalog.py

  # Filter by platform:
  uv run python tools/drama_catalog.py --platform tiktok
  uv run python tools/drama_catalog.py --platform dramabox
  uv run python tools/drama_catalog.py --platform reelshort

  # Inspect episodes and preview for a specific drama by ID:
  uv run python tools/drama_catalog.py --inspect 7684287182416417813
"""

import argparse
import sys

from app.services.drama_catalog_service import DramaCatalogService


def main():
    parser = argparse.ArgumentParser(
        description="CLI tool to fetch, view, and preview online short dramas from TikTok, DramaBox, and ReelShort."
    )
    parser.add_argument(
        "-p",
        "--platform",
        default="All",
        choices=["All", "TikTok", "DramaBox", "ReelShort"],
        help="Filter dramas by platform (default: All).",
    )
    parser.add_argument(
        "--inspect",
        default=None,
        help="Inspect episodes and preview stream for a drama ID.",
    )
    args = parser.parse_args()

    service = DramaCatalogService()

    if args.inspect:
        print(f"\nSearching for drama ID: {args.inspect}...")
        all_items = service.fetch_all("All")
        target = next((item for item in all_items if item.id == args.inspect or args.inspect in item.url), None)
        if not target:
            # Create ad-hoc item if TikTok ID
            if args.inspect.isdigit():
                from app.services.drama_catalog_service import DramaCatalogItem

                target = DramaCatalogItem(
                    id=args.inspect,
                    title="TikTok Drama",
                    platform="TikTok",
                    url=f"https://www.tiktok.com/shortdrama/episode/{args.inspect}",
                    cover_url="",
                    episodes_count=30,
                    description="",
                )
            else:
                print(f"Error: Drama with ID '{args.inspect}' not found in catalog.", file=sys.stderr)
                return

        print(f"\n=======================================================")
        print(f"Title:     {target.title}")
        print(f"Platform:  {target.platform}")
        print(f"ID:        {target.id}")
        print(f"Episodes:  {target.episodes_count}")
        print(f"URL:       {target.url}")
        print(f"=======================================================")
        print(f"\nSynopsis:\n{target.description}\n")

        print("Fetching episode breakdown and preview stream...")
        service.populate_episodes_and_preview(target)
        if target.preview_video_url:
            print(f"\n▶ Preview Stream Available:\n{target.preview_video_url}\n")
        else:
            print("\nPreview Stream: Not directly exposed (will extract on download)\n")

        if target.episodes:
            print("Episodes List:")
            for ep in target.episodes[:25]:
                status = "🔒 Locked" if ep.is_locked else "🔓 Free"
                dur = f"({ep.duration_seconds}s)" if ep.duration_seconds else ""
                print(f"  [{ep.episode_number:02d}] {ep.title} {dur} [{status}]")
            if len(target.episodes) > 25:
                print(f"  ... and {len(target.episodes) - 25} more episodes.")
        return

    print(f"\nFetching {args.platform} short dramas from live websites...\n")
    items = service.fetch_all(args.platform)

    print(f"Discovered {len(items)} short dramas:\n")
    print(f"{'#':<3} {'Platform':<10} {'Episodes':<10} {'Title':<45} {'ID'}")
    print("-" * 85)
    for idx, item in enumerate(items, start=1):
        trunc_title = item.title[:42] + "..." if len(item.title) > 42 else item.title
        print(f"{idx:<3} {item.platform:<10} {item.episodes_count:<10} {trunc_title:<45} {item.id}")

    print("\nTo inspect a drama and view its episodes/preview, run:")
    print("  uv run python tools/drama_catalog.py --inspect <ID>\n")


if __name__ == "__main__":
    main()

