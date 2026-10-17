"""A tiny in-memory stand-in for the Firestore client: just the calls store.py makes."""
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
    def __init__(self, docs, id):
        self.docs, self.id = docs, id

    def get(self):
        return Snap(self.id, self.docs.get(self.id))

    def set(self, data, merge=False):
        self.docs[self.id] = {**self.docs.get(self.id, {}), **copy.deepcopy(data)} if merge else copy.deepcopy(data)

    def delete(self):
        self.docs.pop(self.id, None)


class Collection:
    def __init__(self, docs):
        self.docs = docs

    def document(self, id):
        return Doc(self.docs, id)

    def stream(self):
        return [Snap(i, d) for i, d in list(self.docs.items())]


class FakeFS:
    def __init__(self):
        self.data = {}

    def collection(self, name):
        return Collection(self.data.setdefault(name, {}))
