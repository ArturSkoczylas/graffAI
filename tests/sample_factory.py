"""Generator syntetycznych plików testowych – każdy z jednym typowym problemem.

Uruchom bezpośrednio, żeby odświeżyć katalog samples/:
    python tests/sample_factory.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

MM = 25.4


def _font(px):
    try:
        return ImageFont.load_default(size=px)
    except TypeError:  # starszy Pillow
        return ImageFont.load_default()


class Canvas:
    """Płótno w mm: (0,0) = lewy górny róg formatu NETTO; spad wychodzi na minus."""

    def __init__(self, trim_w, trim_h, bleed=2.5, dpi=300, bg=(255, 255, 255)):
        self.dpi, self.bleed = dpi, bleed
        self.ppm = dpi / MM
        self.w_px = round((trim_w + 2 * bleed) * self.ppm)
        self.h_px = round((trim_h + 2 * bleed) * self.ppm)
        self.trim_w, self.trim_h = trim_w, trim_h
        self.img = Image.new("RGB", (self.w_px, self.h_px), bg)
        self.d = ImageDraw.Draw(self.img)

    def p(self, x, y):
        return ((x + self.bleed) * self.ppm, (y + self.bleed) * self.ppm)

    def rect(self, x0, y0, x1, y1, fill=None, outline=None, width_mm=0.5):
        self.d.rectangle([*self.p(x0, y0), *self.p(x1, y1)], fill=fill, outline=outline,
                         width=max(1, round(width_mm * self.ppm)) if outline else 0)

    def text(self, x, y, s, size_mm=4, fill=(20, 20, 20)):
        self.d.text(self.p(x, y), s, font=_font(max(8, round(size_mm * self.ppm))), fill=fill)

    def text_block(self, x, y, lines, size_mm=4, gap=1.5):
        for i, s in enumerate(lines):
            self.text(x, y + i * size_mm * gap, s, size_mm)

    def save(self, path, dpi=None, **kw):
        self.img.save(path, dpi=(dpi or self.dpi,) * 2, **kw)
        return path


LOREM = ["Drukarnia Gutenberg", "ul. Miejska 14, Wroclaw", "tel. 730 885 333"]


def build_all(out: Path) -> dict:
    """Tworzy próbki. Zwraca {nazwa: (ścieżka, product_id, oczekiwane_kody, oczekiwany_status)}."""
    out.mkdir(parents=True, exist_ok=True)
    S = {}

    # 1. Poprawna ulotka A5 ze spadami: tło w spadzie, tekst daleko od krawędzi
    c = Canvas(148, 210, bg=(30, 80, 160))
    c.rect(20, 30, 128, 120, fill=(250, 220, 60))
    c.text_block(25, 140, LOREM, 6)
    S["a5_poprawna"] = (c.save(out / "a5_poprawna.jpg", quality=92), "ulotka_a5",
                        {"DPI_OK"}, "OK")

    # 2. Pełne tło, ale plik bez spadów
    c = Canvas(148, 210, bleed=0, bg=(30, 80, 160))
    c.text_block(25, 140, LOREM, 6)
    S["a5_brak_spadow"] = (c.save(out / "a5_brak_spadow.jpg", quality=92), "ulotka_a5",
                           {"NO_BLEED_CONTENT_AT_EDGE"}, "BŁĘDY")

    # 3. Bez spadów, ale białe tło i nic nie dochodzi do krawędzi -> spady niewymagane
    c = Canvas(148, 210, bleed=0)
    c.text_block(20, 20, LOREM, 6)
    c.rect(20, 80, 128, 180, fill=(200, 40, 40))
    S["a5_bez_spadow_biale_tlo"] = (c.save(out / "a5_bez_spadow_biale_tlo.jpg", quality=92),
                                    "ulotka_a5", {"NO_BLEED_OK"}, "OK")

    # 4. Tekst 1,5 mm od dolnej krawędzi cięcia
    c = Canvas(148, 210, bg=(235, 245, 230))
    c.text_block(25, 40, LOREM, 6)
    c.text(40, 210 - 1.5 - 4, "www.gutenberg-drukarnia.pl", 4)
    S["a5_tekst_przy_krawedzi"] = (c.save(out / "a5_tekst_przy_krawedzi.jpg", quality=92),
                                   "ulotka_a5", {"ELEMENT_IN_SAFE_ZONE"}, "OSTRZEŻENIA")

    # 5. Plik ma wymiar ze spadami, ale tło kończy się na linii cięcia (biały spad)
    c = Canvas(148, 210)
    c.rect(0, 0, 148, 210, fill=(30, 80, 160))
    c.text_block(25, 140, LOREM, 6)
    S["a5_tlo_nie_w_spadzie"] = (c.save(out / "a5_tlo_nie_w_spadzie.jpg", quality=92),
                                 "ulotka_a5", {"BLEED_NOT_FILLED"}, "BŁĘDY")

    # 6. Wizytówka 600 dpi z ramką 2 mm od krawędzi
    c = Canvas(90, 50, dpi=600)
    c.rect(2, 2, 88, 48, outline=(20, 20, 20), width_mm=0.4)
    c.text_block(12, 15, LOREM, 3.2)
    S["wizytowka_ramka_za_blisko"] = (c.save(out / "wizytowka_ramka_za_blisko.tif",
                                             compression="tiff_lzw"),
                                      "wizytowka_90x50", {"FRAME_TOO_CLOSE"}, "OSTRZEŻENIA")

    # 7. Wizytówka z ramką w poprawnej odległości (6 mm)
    c = Canvas(90, 50, dpi=600)
    c.rect(6, 6, 84, 44, outline=(20, 20, 20), width_mm=0.4)
    c.text_block(12, 15, LOREM, 3.2)
    S["wizytowka_ramka_ok"] = (c.save(out / "wizytowka_ramka_ok.tif", compression="tiff_lzw"),
                               "wizytowka_90x50", {"FRAME_OK", "DPI_OK"}, "OK")

    # 8. Wizytówka w 200 dpi (wymagane 600)
    c = Canvas(90, 50, dpi=200, bg=(240, 240, 240))
    c.text_block(12, 15, LOREM, 3.2)
    S["wizytowka_niska_rozdzielczosc"] = (c.save(out / "wizytowka_niska_rozdzielczosc.jpg",
                                                 quality=92),
                                          "wizytowka_90x50", {"DPI_TOO_LOW"}, "BŁĘDY")

    # 9. Ulotka A4 składana do DL – tekst przechodzi przez pierwszy big (99 mm)
    c = Canvas(297, 210, bg=(250, 250, 245))
    c.text_block(110, 30, LOREM, 6)                 # panel środkowy – OK
    c.text(80, 120, "PROMOCJA -20% NA WSZYSTKO", 7)  # przez big na 99 mm
    S["dl_tekst_na_bigu"] = (c.save(out / "dl_tekst_na_bigu.jpg", quality=92),
                             "ulotka_a4_skladana_dl", {"ELEMENT_NEAR_FOLD"}, "OSTRZEŻENIA")

    # 10. Poprawna ulotka, ale metadane DPI = 72 (typowe dla eksportów z przeglądarki)
    c = Canvas(148, 210, bg=(30, 80, 160))
    c.text_block(25, 140, LOREM, 6)
    S["a5_metadane_72dpi"] = (c.save(out / "a5_metadane_72dpi.jpg", dpi=72, quality=92),
                              "ulotka_a5", {"META_DPI_IGNORED", "DPI_OK"}, "OK")

    # 11. Kwadratowy plik zgłoszony jako A5
    c = Canvas(150, 150, bleed=0, bg=(30, 80, 160))
    S["a5_zly_format"] = (c.save(out / "a5_zly_format.jpg", quality=92), "ulotka_a5",
                          {"FORMAT_MISMATCH"}, "BŁĘDY")

    # 12. Zdjęcie/tekstura na całym tle, ciągnąca się w spad
    c = Canvas(148, 210)
    rng = np.random.default_rng(7)
    h, w = c.h_px, c.w_px
    yy, xx = np.mgrid[0:h, 0:w]
    base = (np.sin(xx / 9.0) * np.cos(yy / 7.0) * 70 + 140)
    noise = rng.normal(0, 25, (h, w))
    tex = np.clip(base + noise, 0, 255).astype(np.uint8)
    c.img = Image.fromarray(np.stack([tex, (tex * 0.8).astype(np.uint8), 200 - tex // 3], -1))
    c.d = ImageDraw.Draw(c.img)
    c.rect(20, 60, 128, 150, fill=(255, 255, 255))
    c.text_block(25, 70, LOREM, 6)
    S["a5_zdjecie_w_tle"] = (c.save(out / "a5_zdjecie_w_tle.jpg", quality=92), "ulotka_a5",
                             {"DETAIL_NEAR_EDGE"}, "DO_WERYFIKACJI")

    # 13. PNG z przezroczystością
    c = Canvas(148, 210, bleed=0)
    rgba = Image.new("RGBA", c.img.size, (0, 0, 0, 0))
    ImageDraw.Draw(rgba).ellipse([*c.p(30, 50), *c.p(118, 160)], fill=(200, 30, 30, 255))
    rgba.save(out / "a5_przezroczysty.png", dpi=(300, 300))
    S["a5_przezroczysty"] = (out / "a5_przezroczysty.png", "ulotka_a5",
                             {"FORMAT_NOT_ACCEPTED", "IMAGE_NOTE", "NO_BLEED_OK"}, "OSTRZEŻENIA")

    return S


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "samples"
    for name, (p, prod, codes, status) in build_all(target).items():
        print(f"{name:32s} {prod:26s} oczekiwany: {status}")
