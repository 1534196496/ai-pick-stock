import sqlite3

from scripts.backup_database import backup, restore


def test_backup_and_restore_integrity(tmp_path):
    source = tmp_path / "source.db"
    backup_path = tmp_path / "backup.db"
    restored = tmp_path / "restored.db"
    con = sqlite3.connect(source)
    con.execute("CREATE TABLE sample(value TEXT)")
    con.execute("INSERT INTO sample VALUES ('real')")
    con.commit(); con.close()
    backup(source, backup_path)
    restore(backup_path, restored)
    con = sqlite3.connect(restored)
    assert con.execute("SELECT value FROM sample").fetchone()[0] == "real"
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()
