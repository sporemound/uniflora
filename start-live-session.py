import sqlite3

database = r"V:\Projects\missing-interior-source-review-windows\data\interior.db"

with sqlite3.connect(database) as connection:
    before = connection.execute(
        """
        SELECT environment, mode, current_position, version
        FROM game_sessions
        WHERE environment = 'live'
        """
    ).fetchone()

    if before is None:
        raise RuntimeError("No live session found.")

    if before[1] != "locked":
        raise RuntimeError(
            f"Expected live mode 'locked', found {before[1]!r}. Nothing changed."
        )

    connection.execute(
        """
        UPDATE game_sessions
        SET mode = 'running',
            updated_at = CURRENT_TIMESTAMP
        WHERE environment = 'live'
        """
    )
    connection.commit()

    after = connection.execute(
        """
        SELECT environment, mode, current_position, version
        FROM game_sessions
        WHERE environment = 'live'
        """
    ).fetchone()

print("Before:", before)
print("After: ", after)
