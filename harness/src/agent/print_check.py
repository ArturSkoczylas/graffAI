from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, ConfigDict

from .providers.base import ToolCall, ToolSpec

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_PDF_SCRIPTS = REPO_ROOT / "skills" / "pdf-check" / "scripts"
_IMAGE_SCRIPTS = REPO_ROOT / "skills" / "margin-check" / "scripts"
for _p in (_PDF_SCRIPTS, _IMAGE_SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import check_image  # noqa: E402
import check_pdf  # noqa: E402
import margins as M  # noqa: E402

SUPPORTED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "tif", "tiff"}
_RECOVERABLE_ERRORS = (KeyError, ValueError, FileNotFoundError, IsADirectoryError,
                        check_pdf.InvalidPdfError)


@dataclass(frozen=True)
class Attachment:
    filename: str
    content_type: str
    data: bytes


class CheckPrintFileArgs(BaseModel):
    model_config = ConfigDict(frozen=True)

    filename: str
    product: Optional[str] = None


def _tool_description(rules: dict) -> str:
    products = "\n".join(
        f"- {pid}: {p.get('name', pid)} ({p['trim_mm'][0]:g}×{p['trim_mm'][1]:g} mm)"
        for pid, p in sorted(rules["products"].items())
    )
    return (
        "Sprawdź plik do druku (PDF, JPG, PNG, TIFF) załączony do maila wg zasad Drukarni "
        "Gutenberg – format, spady, marginesy, ramki, bigi, rozdzielczość. Wywołaj, gdy w mailu "
        "jest załącznik, który wygląda jak projekt do druku.\n\n"
        "Dla PDF można wywołać bez `product` – dostaniesz sam format i podpowiedź produktu. "
        "Dla obrazów (JPG/PNG/TIFF) `product` jest wymagany – plik graficzny nie zna swojego "
        "rozmiaru w mm, bez produktu nie da się ocenić marginesów.\n\n"
        "WAŻNE: nie widzisz podglądu z naniesionymi liniami, tylko zmierzone dane. Przy wyniku "
        "SPRAWDŹ albo OSTRZEŻENIE ustaw w create_draft needs_human=true i w staff_notes wypisz "
        "konkretne znaleziska – pracownik musi obejrzeć podgląd sam, Ty nie możesz tego "
        "zweryfikować wzrokowo.\n\nProdukty:\n" + products
    )


def build_check_print_file_tool() -> ToolSpec:
    rules = M.load_rules()
    schema = CheckPrintFileArgs.model_json_schema()
    schema["properties"]["product"]["enum"] = sorted(rules["products"])
    return ToolSpec(
        name="check_print_file",
        description=_tool_description(rules),
        input_schema=schema,
    )


def _run_check(file_path: Path, product_id: Optional[str]) -> str:
    rules = M.load_rules()
    ext = file_path.suffix.lower().lstrip(".")

    if ext == "pdf":
        report = check_pdf.check_pdf(file_path, product_id)
        return check_pdf.format_text(report)

    if ext in SUPPORTED_IMAGE_EXTENSIONS:
        if not product_id:
            names = ", ".join(sorted(rules["products"]))
            return ("Ten plik to obraz – bez `product` nie da się ocenić marginesów (plik "
                    f"graficzny nie zna swojego rozmiaru w mm). Dostępne produkty: {names}.")
        product = M.get_product(rules, product_id)
        report = check_image.check_file(file_path, product, rules)
        return check_image.format_text(report)

    return f"Format .{ext} nie jest obsługiwany przez automatyczne sprawdzanie (PDF, JPG, PNG, TIFF)."


def make_check_print_file_executor(attachments: list[Attachment]) -> Callable[[ToolCall], str]:
    by_name = {a.filename: a for a in attachments}

    def executor(call: ToolCall) -> str:
        args = CheckPrintFileArgs.model_validate(call.raw_input)
        attachment = by_name.get(args.filename)
        if attachment is None:
            available = ", ".join(sorted(by_name)) or "(brak załączników)"
            return f"Nie znaleziono załącznika {args.filename!r}. Dostępne: {available}."

        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / args.filename
            file_path.write_bytes(attachment.data)
            try:
                return _run_check(file_path, args.product)
            except _RECOVERABLE_ERRORS as exc:
                return f"Nie udało się sprawdzić pliku {args.filename!r}: {exc}"

    return executor
