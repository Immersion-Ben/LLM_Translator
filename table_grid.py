"""표 HTML(pred_html) ↔ 격자 모델 ↔ python-docx 병합표 (순수 로직)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from bs4 import BeautifulSoup


@dataclass
class GridCell:
    text: str
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1


@dataclass
class TableGrid:
    n_rows: int
    n_cols: int
    cells: list[GridCell] = field(default_factory=list)


def parse_table_html(html: str) -> TableGrid:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return TableGrid(0, 0, [])
    rows = table.find_all("tr")
    cells: list[GridCell] = []
    occupied: set[tuple[int, int]] = set()
    n_cols = 0
    for r, tr in enumerate(rows):
        c = 0
        for td in tr.find_all(["td", "th"]):
            while (r, c) in occupied:
                c += 1
            colspan = int(td.get("colspan", 1) or 1)
            rowspan = int(td.get("rowspan", 1) or 1)
            cells.append(GridCell(td.get_text(strip=True), r, c, rowspan, colspan))
            for dr in range(rowspan):
                for dc in range(colspan):
                    if dr or dc:
                        occupied.add((r + dr, c + dc))
            c += colspan
            n_cols = max(n_cols, c)
    return TableGrid(len(rows), n_cols, cells)
