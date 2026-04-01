import io
import logging
import re
from collections.abc import Sequence

import openpyxl

from brain.db.session import get_db

logger = logging.getLogger(__name__)


def _sanitize_table_name(filename: str) -> str:
    base = filename.rsplit(".", 1)[0].lower()
    base = re.sub(r"[^a-z0-9]+", "_", base)
    base = re.sub(r"_+", "_", base).strip("_")
    name = f"ingest_{base}" if base else "ingest_sheet"
    return name[:63]


def _sanitize_header(cell: object, index: int) -> str:
    if cell is None:
        return f"col_{index}"
    s = str(cell).strip().lower()
    if not s:
        return f"col_{index}"
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        return f"col_{index}"
    return s


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _unique_column_names(raw: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for c in raw:
        if c not in seen:
            seen[c] = 0
            out.append(c)
        else:
            seen[c] += 1
            out.append(f"{c}_{seen[c]}")
    return out


def _row_empty(values: Sequence[object] | None) -> bool:
    if not values:
        return True
    for v in values:
        if v is None:
            continue
        if isinstance(v, str) and v.strip() == "":
            continue
        return False
    return True


async def ingest_excel(
    file_bytes: bytes,
    filename: str,
    doc_id: str,
) -> dict:
    """
    Parse Excel file, create table in jarvis_alpha, insert all rows.
    Returns: {doc_id, table_name, row_count, columns, error}
    """
    wb = None
    try:
        wb = openpyxl.load_workbook(
            io.BytesIO(file_bytes),
            read_only=True,
            data_only=True,
        )
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        header_row = next(rows_iter, None)
        if header_row is None:
            return {"doc_id": doc_id, "error": "empty sheet"}

        raw_headers = [
            _sanitize_header(header_row[i], i) for i in range(len(header_row))
        ]
        column_names = _unique_column_names(raw_headers)
        table_name = _sanitize_table_name(filename)

        col_defs = ", ".join(f"{_quote_ident(c)} TEXT" for c in column_names)
        meta = (
            "_doc_id TEXT, _row_index INTEGER, _ingested_at TIMESTAMPTZ DEFAULT now()"
        )
        create_sql = (
            f"CREATE TABLE IF NOT EXISTS {_quote_ident(table_name)} "
            f"({col_defs}, {meta})"
        )

        row_count = 0
        excel_row_num = 2

        async with get_db("anon") as db:
            await db.execute(create_sql)

            col_list = ", ".join(_quote_ident(c) for c in column_names)
            n = len(column_names)
            ph = ", ".join(f"${i + 1}" for i in range(n))
            insert_sql = (
                f"INSERT INTO {_quote_ident(table_name)} "
                f"({col_list}, _doc_id, _row_index) "
                f"VALUES ({ph}, ${n + 1}, ${n + 2})"
            )

            for row in rows_iter:
                if _row_empty(row):
                    excel_row_num += 1
                    continue
                values: list[str] = []
                for i in range(n):
                    v = row[i] if i < len(row) else None
                    values.append("" if v is None else str(v))
                await db.execute(
                    insert_sql,
                    *values,
                    doc_id,
                    excel_row_num,
                )
                row_count += 1
                excel_row_num += 1

        return {
            "doc_id": doc_id,
            "table_name": table_name,
            "row_count": row_count,
            "columns": column_names,
        }
    except Exception as e:
        logger.exception("ingest_excel failed: %s", e)
        return {"doc_id": doc_id, "error": str(e)}
    finally:
        if wb is not None:
            wb.close()
