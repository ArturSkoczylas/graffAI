# graffAI

Asystent AI (Claude) dla drukarni **Gutenberg / Graffa** – sprawdzanie, czy pliki
klientów są poprawnie przygotowane do druku.

## Źródła plików

| # | Źródło | Moduł | Status |
|---|---|---|---|
| 1 | PDF | (osobny moduł – w przygotowaniu) | ⏳ |
| 2 | Pliki graficzne: JPG, PNG, TIFF | `skills/margin-check/scripts/check_image.py` | ✅ v0.1 |
| 3 | Linki do Canvy | `skills/margin-check/scripts/canva_link.py` | ✅ v0.1 (weryfikacja linku + lista kontrolna) |

## Struktura

```
graffAI/
├── skills/margin-check/        # skill dla Claude'a – samodzielny, gotowy do spakowania
│   ├── SKILL.md                # instrukcje: kiedy i jak sprawdzać, jak odpowiadać klientowi
│   ├── rules.yaml              # zasady drukarni: spady, marginesy, DPI, produkty
│   └── scripts/
│       ├── margins.py          # wspólny silnik analizy (używany też przez PDF)
│       ├── check_image.py      # CLI: pliki graficzne
│       └── canva_link.py       # CLI: linki Canva
├── tests/                      # pytest + generator próbek
├── samples/                    # przykładowe pliki z typowymi błędami
└── docs/zasady-drukarni.md     # wymagania drukarni (źródło reguł)
```

## Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# lista produktów
python skills/margin-check/scripts/check_image.py --list-products

# sprawdzenie pliku + podgląd z naniesionymi liniami
python skills/margin-check/scripts/check_image.py samples/a5_tekst_przy_krawedzi.jpg \
    --product ulotka_a5 --preview out/

# link do Canvy
python skills/margin-check/scripts/canva_link.py "https://www.canva.com/design/DAG.../edit" \
    --product ulotka_a5

# testy
pytest -q
```

`--json` zwraca wynik w formacie do dalszego przetwarzania (np. backend asystenta).

## Co sprawdza skrypt dla plików graficznych

1. **Format i spady**: rozpoznaje, czy plik to format netto, czy netto + 2,5 mm spadu.
   Rzeczywiste DPI liczy z wymiarów produktu, bo metadane bywają błędne (np. 72 dpi).
2. **Spady**: czy tło wchodzi w spad. Bez spadów: czy nic nie dochodzi do krawędzi,
   a jeśli nie, spady nie są wymagane (zgodnie z zasadami drukarni).
3. **Strefa bezpieczeństwa 3 mm**: elementy (tekst, logo) za blisko linii cięcia.
4. **Ramki 5 mm**: linie równoległe do krawędzi za blisko cięcia.
5. **Bigi**: treść i ramki przy zgięciach (produkty składane).
6. **Rozdzielczość**: 300 dpi, wizytówki 600 dpi.
7. Format pliku, przezroczystość, RGB/CMYK, wielostronicowe TIFF-y.

Wyniki mają poziomy `BŁĄD`, `OSTRZEŻENIE`, `SPRAWDŹ` i `INFO`. Wynik `SPRAWDŹ` oznacza,
że skrypt nie odróżni tła od ważnego elementu. Wtedy Claude ogląda wygenerowany podgląd
i sam ocenia.

## Integracja z PDF (źródło 1)

Silnik działa na rastrze o znanej geometrii, więc moduł PDF może użyć tej samej logiki:

```python
import margins as M
rules = M.load_rules()
product = M.get_product(rules, "ulotka_a5")
# rgb: numpy uint8 (H, W, 3) – strona zrasteryzowana w obszarze BleedBox
layout = M.layout_from_known(rgb.shape[1], rgb.shape[0], product, bleed_mm=2.5)
findings = M.analyze_raster(rgb, layout, product) + M.check_resolution(layout, product)
```

Uwaga: PDF z Canvy eksportowany ze **znacznikami cięcia** ma MediaBox większy niż format
ze spadami. Geometrię trzeba brać z TrimBox i BleedBox.

## Skill dla Claude'a

Folder `skills/margin-check/` jest samodzielny. Można go spakować do ZIP i dodać jako skill
w Claude (Ustawienia → Skills) albo użyć przez API / Agent SDK.

```bash
cd skills && zip -r margin-check.zip margin-check -x "*/__pycache__/*"
```

## Dalsze kroki

- [ ] Potwierdzić z drukarnią reguły dla wielkiego formatu (banery, płótna, plakaty > A3)
- [ ] Testy na prawdziwych plikach klientów (anonimizowanych) – dostroić progi w `margins.py`
- [ ] Canva Connect API: automatyczny eksport projektu do PDF (wymaga aplikacji OAuth)
- [ ] Połączenie z modułem PDF
