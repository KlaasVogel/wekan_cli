"""Typed objects built from a board export (``GET /api/boards/:b/export``).

The export holds everything a command needs in one call: cards with their ``cardNumber``, lists with their
``wipLimit``, swimlanes, labels, checklists, checklist items and the members' usernames.
"""

from dataclasses import dataclass, field
from typing import Any, cast

Json = dict[str, Any]


def _live(obj: Json) -> bool:
    """False for soft-deleted objects (``deletedAt`` set). Archived objects are kept; callers decide."""
    return not obj.get("deletedAt")


def _sort_key(index: int, obj: Json) -> tuple[float, int]:
    """Sort by Wekan's ``sort`` field, keeping export order for objects without one (new lists get ``None``)."""
    sort = obj.get("sort")
    return (float(sort) if isinstance(sort, int | float) else float("inf"), index)


def _ordered(items: list[Json]) -> list[Json]:
    return [obj for _, obj in sorted(enumerate(items), key=lambda pair: _sort_key(*pair))]


@dataclass(frozen=True)
class WipLimit:
    """A list's work-in-progress limit. Without a ``soft`` flag, Wekan treats an enabled limit as hard."""

    value: int
    enabled: bool
    soft: bool

    @property
    def hard(self) -> bool:
        """True when the limit is enabled and not soft."""
        return self.enabled and not self.soft

    @classmethod
    def from_json(cls, data: Any) -> "WipLimit | None":
        """Build from the export's ``wipLimit``, or None when there is no enabled limit."""
        if not isinstance(data, dict):
            return None
        limit = cast(dict[str, Any], data)
        if not limit.get("enabled"):
            return None
        return cls(value=int(limit.get("value", 0)), enabled=True, soft=bool(limit.get("soft", False)))


@dataclass(frozen=True)
class Label:
    id: str
    name: str
    color: str


@dataclass(frozen=True)
class User:
    id: str
    username: str
    fullname: str


@dataclass(frozen=True)
class Swimlane:
    id: str
    title: str
    archived: bool


@dataclass(frozen=True)
class WList:
    """A Wekan list (named ``WList`` to avoid clashing with Python's ``list``)."""

    id: str
    title: str
    swimlane_id: str
    archived: bool
    wip: WipLimit | None


@dataclass(frozen=True)
class Item:
    id: str
    checklist_id: str
    title: str
    finished: bool


@dataclass(frozen=True)
class Checklist:
    id: str
    card_id: str
    title: str
    items: tuple[Item, ...]

    @property
    def done(self) -> int:
        """Number of finished items."""
        return sum(item.finished for item in self.items)


@dataclass(frozen=True)
class Card:
    id: str
    number: int
    title: str
    list_id: str
    swimlane_id: str
    label_ids: tuple[str, ...]
    assignee_ids: tuple[str, ...]
    description: str
    archived: bool


@dataclass(frozen=True)
class Board:
    """One board, as read from its export. Lists, cards and checklists keep Wekan's display order."""

    id: str
    title: str
    swimlanes: tuple[Swimlane, ...]
    lists: tuple[WList, ...]
    cards: tuple[Card, ...]
    checklists: tuple[Checklist, ...]
    labels: dict[str, Label] = field(default_factory=dict[str, Label])
    users: dict[str, User] = field(default_factory=dict[str, User])

    @classmethod
    def from_export(cls, data: Json) -> "Board":
        """Build a board from an export, dropping soft-deleted objects.

        Args:
            data: The parsed export JSON.

        Returns:
            The board.
        """
        items_by_checklist: dict[str, list[Item]] = {}
        for raw in _ordered([i for i in data.get("checklistItems", []) if _live(i)]):
            item = Item(
                id=raw["_id"],
                checklist_id=raw.get("checklistId", ""),
                title=raw.get("title", ""),
                finished=bool(raw.get("isFinished")),
            )
            items_by_checklist.setdefault(item.checklist_id, []).append(item)
        return cls(
            id=data["_id"],
            title=data.get("title", ""),
            swimlanes=tuple(
                Swimlane(id=s["_id"], title=s.get("title", ""), archived=bool(s.get("archived")))
                for s in _ordered([s for s in data.get("swimlanes", []) if _live(s)])
            ),
            lists=tuple(
                WList(
                    id=raw["_id"],
                    title=raw.get("title", ""),
                    swimlane_id=raw.get("swimlaneId", ""),
                    archived=bool(raw.get("archived")),
                    wip=WipLimit.from_json(raw.get("wipLimit")),
                )
                for raw in _ordered([lst for lst in data.get("lists", []) if _live(lst)])
            ),
            cards=tuple(
                Card(
                    id=raw["_id"],
                    number=int(raw.get("cardNumber") or 0),
                    title=raw.get("title", ""),
                    list_id=raw.get("listId", ""),
                    swimlane_id=raw.get("swimlaneId", ""),
                    label_ids=tuple(raw.get("labelIds") or ()),
                    assignee_ids=tuple(raw.get("assignees") or ()),
                    description=raw.get("description") or "",
                    archived=bool(raw.get("archived")),
                )
                for raw in _ordered([c for c in data.get("cards", []) if _live(c)])
            ),
            checklists=tuple(
                Checklist(
                    id=raw["_id"],
                    card_id=raw.get("cardId", ""),
                    title=raw.get("title", ""),
                    items=tuple(items_by_checklist.get(raw["_id"], [])),
                )
                for raw in _ordered([c for c in data.get("checklists", []) if _live(c)])
            ),
            labels={
                raw["_id"]: Label(id=raw["_id"], name=raw.get("name") or "", color=raw.get("color") or "")
                for raw in data.get("labels", [])
            },
            users={
                raw["_id"]: User(
                    id=raw["_id"],
                    username=raw.get("username", ""),
                    fullname=str(cast(dict[str, Any], raw.get("profile") or {}).get("fullname", "")),
                )
                for raw in data.get("users", [])
            },
        )

    def list_by_id(self, list_id: str) -> WList | None:
        """Return the list with this ID, or None."""
        return next((lst for lst in self.lists if lst.id == list_id), None)

    def cards_in(self, list_id: str, include_archived: bool = False) -> list[Card]:
        """Return the cards in a list, in display order."""
        return [c for c in self.cards if c.list_id == list_id and (include_archived or not c.archived)]

    def checklists_of(self, card_id: str) -> list[Checklist]:
        """Return a card's checklists, in display order."""
        return [cl for cl in self.checklists if cl.card_id == card_id]

    def label_name(self, label_id: str) -> str:
        """Return a label's name (or its colour when it has no name)."""
        label = self.labels.get(label_id)
        return (label.name or label.color) if label else label_id

    def username(self, user_id: str) -> str:
        """Return a member's username, or the ID when the export doesn't know it."""
        user = self.users.get(user_id)
        return user.username if user else user_id
