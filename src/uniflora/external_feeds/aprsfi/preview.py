from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .config import AprsFiSettings
from .service import AprsFiExteriorService


async def _run(targets_path: Path) -> None:
    settings = AprsFiSettings.from_environment(targets_path)
    service = AprsFiExteriorService(settings)
    try:
        report = await service.report(force_refresh=True)
        print(report.text)
    finally:
        await service.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview one user-triggered aprs.fi exterior report"
    )
    parser.add_argument(
        "--targets",
        type=Path,
        required=True,
        help="Path to targets.json",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.targets))


if __name__ == "__main__":
    main()
