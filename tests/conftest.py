"""Shared fixtures: invalid input data for the pdf-check modules."""
import io

import pytest
from pypdf import PdfWriter

# Arguments that are not a path at all
NOT_A_PATH = [None, 123, 3.5, True, b"plik.pdf", ["plik.pdf"], {"path": "plik.pdf"}, object()]


def _pdf_bytes(**encrypt) -> bytes:
    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    if encrypt:
        w.encrypt(algorithm="RC4-128", **encrypt)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


@pytest.fixture
def password_pdf(tmp_path):
    """PDF that only opens once a password is given."""
    path = tmp_path / "haslo.pdf"
    path.write_bytes(_pdf_bytes(user_password="tajne"))
    return path


@pytest.fixture
def owner_locked_pdf(tmp_path):
    """PDF with an edit lock (owner password) - opens without a password."""
    path = tmp_path / "blokada.pdf"
    path.write_bytes(_pdf_bytes(user_password="", owner_password="wlasciciel"))
    return path


@pytest.fixture
def truncated_pdf(tmp_path):
    """PDF truncated halfway through, e.g. an interrupted attachment download."""
    data = _pdf_bytes()
    path = tmp_path / "uciety.pdf"
    path.write_bytes(data[: len(data) // 2])
    return path


@pytest.fixture
def not_pdf_files(tmp_path):
    """Files with a .pdf extension that are not actually a PDF."""
    files = {
        "pusty": b"",
        "jpg": b"\xff\xd8\xff\xe0\x00\x10JFIF to jest JPG",
        "tekst": "Dzień dobry, w załączniku projekt".encode(),
        "html": b"<html><body>Bramka pocztowa: plik wygasl</body></html>",
        "sam_naglowek": b"%PDF-1.7\n",
    }
    paths = {}
    for name, data in files.items():
        paths[name] = tmp_path / f"{name}.pdf"
        paths[name].write_bytes(data)
    return paths
