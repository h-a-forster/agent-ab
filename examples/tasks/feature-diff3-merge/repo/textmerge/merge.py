"""Three-way merge. Currently file-level only: a side that did not change loses."""
from .lines import join_lines, split_lines


class MergeConflict(Exception):
    """Both sides changed the text differently."""


def merge_text(base, ours, theirs):
    """Return the merged text, or raise MergeConflict."""
    if ours == theirs:
        return ours
    if ours == base:
        return theirs
    if theirs == base:
        return ours
    raise MergeConflict("both sides changed the file")
