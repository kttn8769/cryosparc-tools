from typing import TYPE_CHECKING, Any, Dict, Generic, Iterable, List, Mapping, Tuple, TypeVar

import numpy as n

if TYPE_CHECKING:
    from .dataset import Dataset


class Row(Mapping):
    """
    Provides row-by-row access to the datasert
    """

    def __init__(self, dataset: "Dataset", idx: int):
        self.idx = idx
        self.dataset = dataset
        # note - don't keep around a ref to dataset.data because then when dataset.data changes (add field)
        # the already existing items will be referring to the old dataset.data!

    def __len__(self):
        return len(self.dataset.fields())

    def __getitem__(self, key: str):
        return self.dataset[key][self.idx]

    def __setitem__(self, key: str, value):
        self.dataset[key][self.idx] = value

    def __contains__(self, key: str):
        return key in self.dataset

    def __iter__(self):
        return iter(self.dataset.fields())

    def get(self, key, default=None):
        if key in self:
            return self[key]
        return default

    def get_item(self, key, default=None):
        return self.dataset[key][self.idx] if key in self else default

    def to_list(self, exclude_uid=False):
        """Convert into a list of native python types, ordered the same way as the fields"""
        return [self.get_item(key) for key in self.dataset.fields() if not exclude_uid or key != "uid"]

    def to_dict(self):
        return {key: self[key] for key in self.dataset.fields()}

    def to_item_dict(self):
        """Like to_dict, but all values are native python types"""
        return {key: self.get_item(key) for key in self.dataset.fields()}

    def from_dict(self, d):
        for k in self.dataset.fields():
            self[k] = d[k]


R = TypeVar("R", bound=Row)


class Spool(List[R], Generic[R]):
    """
    List-like database row accessor class with support for splitting and
    randomizing based on row fields
    """

    def __init__(self, items: Iterable[R], rng: n.random.Generator = n.random.default_rng()):
        self.indexes = None
        self.random = rng
        self.extend(items)

    def set_random(self, rng: n.random.Generator):
        self.random = rng

    # -------------------------------------------------- Spooling and Splitting
    def split(self, num: int, random=True, prefix=None):
        """Return two SpoolingLists with the split portions"""
        if random:
            idxs = self.random.permutation(len(self))
        else:
            idxs = n.arange(len(self))
        d1 = Spool(items=(self[i] for i in idxs[:num]), rng=self.random)
        d2 = Spool(items=(self[i] for i in idxs[num:]), rng=self.random)
        if prefix is not None:
            field = prefix + "/split"
            for img in d1:
                img[field] = 0
            for img in d2:
                img[field] = 1
        return d1, d2

    def split_half_in_order(self, prefix: str, random=True):
        if random:
            splitvals = n.random.randint(2, size=len(self))
        else:
            splitvals = n.arange(len(self)) % 2
        for idx, p in enumerate(self):
            p[prefix + "/split"] = splitvals[idx]
        d1 = Spool(items=(p for p in self if p[prefix + "/split"] == 0), rng=self.random)
        d2 = Spool(items=(p for p in self if p[prefix + "/split"] == 1), rng=self.random)
        return d1, d2

    def split_into_quarter(self, num: int, seed: int):
        """Return two Spools with the split portions"""
        idxs = n.random.default_rng(seed=seed).permutation(len(self))
        d1 = Spool(items=(self[i] for i in idxs[:num]), rng=n.random.default_rng(seed=seed))
        d2 = Spool(items=(self[i] for i in idxs[num:]), rng=n.random.default_rng(seed=seed))
        return d1, d2

    def split_with_split(self, num: int, random=True, prefix=None, split=0):
        """Return two Spools with the split portions"""
        if random:
            idxs = self.random.permutation(len(self))
        else:
            idxs = n.arange(len(self))
        d1 = Spool(items=(self[i] for i in idxs[:num]), rng=self.random)
        d2 = Spool(items=(self[i] for i in idxs[num:]), rng=self.random)
        if prefix is not None:
            field = prefix + "/split"
            for img in d1:
                img[field] = split
            for img in d2:
                img[field] = split
        return d1, d2

    def split_by_splits(self, prefix="alignments"):
        """Return two Spools with the split portions"""
        idxs = n.arange(len(self))
        field = "split"
        if prefix is not None:
            field = prefix + "/split"
        d1 = Spool(items=(self[i] for i in idxs if self[i][field] == 0), rng=self.random)
        d2 = Spool(items=(self[i] for i in idxs if self[i][field] == 1), rng=self.random)
        return d1, d2

    def split_from_field(self, field: str, vals: Tuple[Any, Any] = (0, 1)):
        """split into two from pre recorded split in field, between given vals"""
        d1 = Spool((img for img in self if img[field] == vals[0]), rng=self.random)
        d2 = Spool((img for img in self if img[field] == vals[1]), rng=self.random)
        return d1, d2

    def split_by(self, field: str) -> Dict[Any, List[R]]:
        items = {}
        for item in self:
            val = item[field]
            curr = items.get(val, [])
            curr.append(item)
            items[val] = curr
        return items

    def get_random_subset(self, num: int):
        "Just a randomly selected subset, without replacement. Returns a list."
        assert num <= len(self), "Not Enough Images!"
        idxs = self.random.choice(len(self), size=num, replace=False)
        return [self[i] for i in idxs]

    def setup_spooling(self, random=True):
        """Setup indices and minibatches for spooling"""
        if random:
            self.indexes = self.random.permutation(len(self))
        else:
            self.indexes = n.arange(len(self))
        self.spool_index = 0

    def spool(self, num: int, peek: bool = False):
        """Return a list consisting of num randomly selected elements.
        Advance the spool.
        Return self.minibatch_size elements if num is None.
        if peek is true, don't advance the spool, just return the first num elements.
        """
        if self.indexes is None:
            self.setup_spooling()
        assert self.indexes is not None
        if num >= len(self):  # asking for too many
            return [self[i] for i in range(len(self))]  # just return self, no random order.
        current_indices = n.arange(self.spool_index, self.spool_index + num) % len(self.indexes)
        if not peek:
            self.spool_index = (self.spool_index + num) % len(self.indexes)
        return [self[self.indexes[i]] for i in current_indices]

    def make_batches(self, num: int = 200):
        """
        Return a list of lists, each one being a consecutive set of num images.
        """
        return [self[idx : idx + num] for idx in n.arange(0, len(self), num)]

    def __str__(self):
        s = f"{type(self).__name__} object with {len(self)} items."
        return s
