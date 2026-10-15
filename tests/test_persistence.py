from concurrent.futures import ThreadPoolExecutor
import sqlite3

from hybrid_log_classifier.domain import Classification, ClassificationTier, Category
from hybrid_log_classifier.persistence import ClassificationStore


def test_concurrent_writes_are_persisted(tmp_path):
    db_path = tmp_path / "runtime" / "classifications.db"
    store = ClassificationStore(db_path)

    def write(index):
        store.save(
            f"failed login user={index}",
            Classification(Category.SECURITY, ClassificationTier.RULE, 1.0, "test", 0.1),
        )

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(write, range(64)))

    with sqlite3.connect(db_path) as connection:
        total = connection.execute("SELECT COUNT(*) FROM classifications").fetchone()[0]
    assert total == 64
