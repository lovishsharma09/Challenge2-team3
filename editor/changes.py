"""What actually changed between two drafts: concrete before -> after items, so the editor sees the correction itself and not
only the original complaint. Pure functions, no I/O."""
from __future__ import annotations

import difflib

from .render import ingredient_text

SCALARS = (("title", "Title"), ("subtitle", "Subtitle"), ("servings", "Servings"),
           ("prep_time_minutes", "Preparation time (min)"), ("cook_time_minutes", "Cooking time (min)"))
MAX_CHANGES = 60


def _aligned(before: list[str], after: list[str]) -> list[tuple[int | None, int | None]]:
    """Positions (index in before, index in after) of every differing item; replaced items are paired up in order."""
    out: list[tuple[int | None, int | None]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=before, b=after, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        for k in range(max(i2 - i1, j2 - j1)):
            out.append((i1 + k if i1 + k < i2 else None, j1 + k if j1 + k < j2 else None))
    return out


def diff_bundles(before: dict | None, after: dict) -> list[dict]:
    """Changes per recipe: scalar fields, ingredients and steps. Each item: recipe_index, recipe_title, where, before, after
    (None means 'nothing', i.e. an item was added or removed)."""
    if not before:
        return []
    changes: list[dict] = []
    for idx, (b, a) in enumerate(zip(before.get("recipes", []), after.get("recipes", []))):
        title = str(a.get("title") or b.get("title") or f"Recipe {idx + 1}")

        def add(where, old, new):
            changes.append({"recipe_index": idx, "recipe_title": title, "where": where,
                            "before": None if old is None else str(old), "after": None if new is None else str(new)})

        for key, label in SCALARS:
            if b.get(key) != a.get(key):
                add(label, b.get(key), a.get(key))
        ib, ia = [ingredient_text(i) for i in b.get("ingredients", [])], [ingredient_text(i) for i in a.get("ingredients", [])]
        for x, y in _aligned(ib, ia):
            add("Ingredient", ib[x] if x is not None else None, ia[y] if y is not None else None)
        sb, sa = [str(t) for t in b.get("steps", [])], [str(t) for t in a.get("steps", [])]
        for x, y in _aligned(sb, sa):
            add(f"Step {(y if y is not None else x) + 1}", sb[x] if x is not None else None, sa[y] if y is not None else None)
    return changes[:MAX_CHANGES]
