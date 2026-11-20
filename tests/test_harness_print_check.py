"""Tests for harness/agent/print_check.py - the check_print_file tool (PDF/image from an email)."""
import io
import sys
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.src.agent import print_check as PC  # noqa: E402
from harness.src.agent.providers.base import ToolCall  # noqa: E402


def _tiny_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=420, height=595)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _tiny_image_bytes(fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(buf, format=fmt)
    return buf.getvalue()


def _attachment(filename, data, content_type="application/octet-stream"):
    return PC.Attachment(filename=filename, content_type=content_type, data=data)


def _call(filename, product=None):
    args = {"filename": filename}
    if product is not None:
        args["product"] = product
    return ToolCall(id="c1", name="check_print_file", raw_input=args)


# --------------------------------------------------------------------------- build_check_print_file_tool
def test_build_tool_lists_known_products_in_schema():
    tool = PC.build_check_print_file_tool()
    assert tool.name == "check_print_file"
    assert "ulotka_a5" in tool.input_schema["properties"]["product"]["enum"]


def test_build_tool_schema_has_filename_and_product():
    tool = PC.build_check_print_file_tool()
    assert {"filename", "product"} <= set(tool.input_schema["properties"])


# --------------------------------------------------------------------------- executor: happy paths
def test_executor_pdf_without_product_returns_text_report():
    executor = PC.make_check_print_file_executor([_attachment("projekt.pdf", _tiny_pdf_bytes())])
    result = executor(_call("projekt.pdf"))
    assert "projekt.pdf" in result
    assert "WYNIK" in result


def test_executor_pdf_with_known_product_returns_text_report():
    executor = PC.make_check_print_file_executor([_attachment("ulotka.pdf", _tiny_pdf_bytes())])
    result = executor(_call("ulotka.pdf", product="ulotka_a5"))
    assert "Ulotka A5" in result


def test_executor_image_with_product_returns_text_report():
    executor = PC.make_check_print_file_executor([_attachment("wizytowka.png", _tiny_image_bytes())])
    result = executor(_call("wizytowka.png", product="wizytowka_90x50"))
    assert "WYNIK" in result


# --------------------------------------------------------------------------- executor: invalid input
def test_executor_unknown_filename_lists_available():
    executor = PC.make_check_print_file_executor([_attachment("a.pdf", _tiny_pdf_bytes())])
    result = executor(_call("nie-taki-plik.pdf"))
    assert "nie-taki-plik.pdf" in result
    assert "a.pdf" in result


def test_executor_no_attachments_reports_none_available():
    executor = PC.make_check_print_file_executor([])
    result = executor(_call("cokolwiek.pdf"))
    assert "brak załączników" in result


def test_executor_image_without_product_asks_for_one():
    executor = PC.make_check_print_file_executor([_attachment("zdjecie.jpg", _tiny_image_bytes("JPEG"))])
    result = executor(_call("zdjecie.jpg"))
    assert "product" in result
    assert "ulotka_a5" in result  # hint of available products


def test_executor_unknown_product_id_returns_error_text_not_raises():
    executor = PC.make_check_print_file_executor([_attachment("a.pdf", _tiny_pdf_bytes())])
    result = executor(_call("a.pdf", product="nie-ma-takiego-produktu"))
    assert "a.pdf" in result


def test_executor_corrupted_pdf_returns_error_text_not_raises():
    executor = PC.make_check_print_file_executor([_attachment("zle.pdf", b"to nie jest PDF")])
    result = executor(_call("zle.pdf"))
    assert "zle.pdf" in result


def test_executor_unsupported_extension_returns_explanatory_text():
    executor = PC.make_check_print_file_executor([_attachment("plik.docx", b"xyz")])
    result = executor(_call("plik.docx"))
    assert "docx" in result
    assert "PDF" in result


def test_executor_malformed_tool_args_raises_validation_error():
    executor = PC.make_check_print_file_executor([_attachment("a.pdf", _tiny_pdf_bytes())])
    call = ToolCall(id="c", name="check_print_file", raw_input={})  # brak filename
    with pytest.raises(Exception):
        executor(call)
