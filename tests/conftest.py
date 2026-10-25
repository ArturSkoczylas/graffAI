"""Wspólne fixtures: błędne dane wejściowe dla modułów pdf-check."""
import io

import pytest
from pypdf import PdfWriter

# Argumenty, które w ogóle nie są ścieżką
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
    """PDF otwierany dopiero po podaniu hasła."""
    path = tmp_path / "haslo.pdf"
    path.write_bytes(_pdf_bytes(user_password="tajne"))
    return path


@pytest.fixture
def owner_locked_pdf(tmp_path):
    """PDF z blokadą edycji (hasło właściciela) – otwiera się bez hasła."""
    path = tmp_path / "blokada.pdf"
    path.write_bytes(_pdf_bytes(user_password="", owner_password="wlasciciel"))
    return path


@pytest.fixture
def truncated_pdf(tmp_path):
    """PDF ucięty w połowie, np. przerwane pobieranie załącznika."""
    data = _pdf_bytes()
    path = tmp_path / "uciety.pdf"
    path.write_bytes(data[: len(data) // 2])
    return path


@pytest.fixture
def not_pdf_files(tmp_path):
    """Pliki z rozszerzeniem .pdf, które PDF-em nie są."""
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
