import sqlite3
from pathlib import Path

from uniflora.config import Settings

root = Path(r"V:\Projects\missing-interior-source-review-windows")
database = root / "data" / "interior.db"
settings = Settings()

expected = {
    "guild_id": settings.discord_guild_id,
    "live_channel_id": settings.live_puzzle_channel_id,
    "test_channel_id": settings.test_puzzle_channel_id,
    "diagnostic_channel_id": settings.diagnostic_channel_id,
}

print("Writing persisted routing from .env:")
for key, value in expected.items():
    print(f"  {key} = {value}")

with sqlite3.connect(database) as connection:
    rows = connection.execute(
        "SELECT id FROM guild_configurations"
    ).fetchall()

    if len(rows) != 1:
        raise RuntimeError(
            f"Expected exactly one guild_configurations row; found {len(rows)}. "
            "No changes were committed."
        )

    row_id = rows[0][0]

    connection.execute(
        """
        UPDATE guild_configurations
        SET guild_id = ?,
            live_channel_id = ?,
            test_channel_id = ?,
            diagnostic_channel_id = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            expected["guild_id"],
            expected["live_channel_id"],
            expected["test_channel_id"],
            expected["diagnostic_channel_id"],
            row_id,
        ),
    )
    connection.commit()

    saved = connection.execute(
        """
        SELECT guild_id, live_channel_id, test_channel_id,
               diagnostic_channel_id
        FROM guild_configurations
        WHERE id = ?
        """,
        (row_id,),
    ).fetchone()

print("\nSaved routing:")
print("  guild_id =", saved[0])
print("  live_channel_id =", saved[1])
print("  test_channel_id =", saved[2])
print("  diagnostic_channel_id =", saved[3])
