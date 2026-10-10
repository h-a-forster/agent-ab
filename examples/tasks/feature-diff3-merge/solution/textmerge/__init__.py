from .diff import apply_diff, diff
from .lines import join_lines, split_lines
from .merge import MergeConflict, MergeResult, merge3, merge_text

__all__ = ["MergeConflict", "MergeResult", "apply_diff", "diff", "join_lines", "merge3",
           "merge_text", "split_lines"]
