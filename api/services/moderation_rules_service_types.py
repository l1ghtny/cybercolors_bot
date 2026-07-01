from dataclasses import dataclass


@dataclass
class ParsedRule:
    marker: str | None
    code: str | None
    title: str
    description: str | None
    sort_order: int
