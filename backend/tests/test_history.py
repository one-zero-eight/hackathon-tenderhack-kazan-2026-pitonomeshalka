"""Search history deduplication and ordering."""

from backend.src.history import SearchHistoryStore


class FakeRedis:
    """Minimal list commands; pipelines execute immediately in order."""

    def __init__(self):
        self.lists: dict[str, list[str]] = {}

    def from_url(self, url, **_):
        return self

    def ping(self):
        return True

    def pipeline(self):
        owner = self

        class Pipe:
            def __init__(self):
                self.ops = []

            def lrem(self, key, count, value):
                self.ops.append(("lrem", key, count, value))

            def lpush(self, key, value):
                self.ops.append(("lpush", key, value))

            def ltrim(self, key, start, stop):
                self.ops.append(("ltrim", key, start, stop))

            def expire(self, key, ttl):
                self.ops.append(("expire", key, ttl))

            def execute(self):
                for op in self.ops:
                    getattr(owner, "_" + op[0])(*op[1:])

        return Pipe()

    def _lrem(self, key, count, value):
        items = self.lists.get(key, [])
        for _ in range(abs(count)) if count else range(len(items)):
            if value in items:
                items.remove(value)

    def _lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def _ltrim(self, key, start, stop):
        self.lists[key] = self.lists.get(key, [])[start:stop + 1]

    def _expire(self, key, ttl):
        pass

    def lrange(self, key, start, stop):
        items = self.lists.get(key, [])
        # Redis LRANGE 0 -1 means "to the end"; Python [-1] would drop the last.
        return items[start:] if stop == -1 else items[start:stop + 1]


def make_store():
    fake = FakeRedis()
    return SearchHistoryStore.__new__(SearchHistoryStore), fake


def wire(store, fake):
    store._client = fake
    store._max_items = 5
    store._ttl_seconds = 604800


def test_repeated_identical_query_stays_single():
    store, fake = make_store()
    wire(store, fake)
    store.add("s", "Дрель аккумуляторная")
    store.add("s", "Дрель аккумуляторная")
    assert store.get("s") == ["Дрель аккумуляторная"]


def test_query_differing_only_by_case_and_spaces_replaces_old():
    store, fake = make_store()
    wire(store, fake)
    store.add("s", "Письменный стол  прямой каркас")
    store.add("s", "письменный стол прямой каркас")
    assert store.get("s") == ["письменный стол прямой каркас"]


def test_yo_and_e_spellings_are_one_query():
    store, fake = make_store()
    wire(store, fake)
    store.add("s", "Ёлка зелёная")
    store.add("s", "Елка зеленая")
    assert len(store.get("s")) == 1


def test_distinct_queries_keep_both_newest_first():
    store, fake = make_store()
    wire(store, fake)
    store.add("s", "Дрель")
    store.add("s", "Стол")
    assert store.get("s") == ["Стол", "Дрель"]


def test_whitespace_only_query_is_ignored():
    store, fake = make_store()
    wire(store, fake)
    store.add("s", "   ")
    assert store.get("s") == []
