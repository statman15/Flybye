"""A tiny in-memory stand-in for the Firestore client: just the calls the code makes. Documents live in one flat dict by path."""
import copy


class Snap:
    def __init__(self, id, data):
        self.id, self._data = id, data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return copy.deepcopy(self._data)


class Doc:
    def __init__(self, fs, path):
        self.fs, self.path, self.id = fs, path, path.rsplit("/", 1)[-1]

    def get(self):
        return Snap(self.id, self.fs.data.get(self.path))

    def set(self, data, merge=False):
        self.fs.data[self.path] = {**self.fs.data.get(self.path, {}), **copy.deepcopy(data)} if merge else copy.deepcopy(data)

    def delete(self):
        self.fs.data.pop(self.path, None)

    def collection(self, name):
        return Collection(self.fs, f"{self.path}/{name}")


class Collection:
    def __init__(self, fs, path):
        self.fs, self.path = fs, path

    def document(self, id):
        return Doc(self.fs, f"{self.path}/{id}")

    def stream(self):
        n = self.path.count("/") + 2
        return [Snap(p.rsplit("/", 1)[-1], d) for p, d in list(self.fs.data.items())
                if p.startswith(self.path + "/") and p.count("/") + 1 == n]


class FakeFS:
    def __init__(self):
        self.data = {}

    def collection(self, name):
        return Collection(self, name)

    def docs(self, path):
        """id -> data of one collection, for asserting in tests."""
        return {s.id: s.to_dict() for s in self.collection(path).stream()}


def new_store(sid="s1", fs=None):
    from flybye.store import Store
    return Store(fs or FakeFS(), sid)
