---
name: pdf-check
description: Sprawdza PDF do druku według zasad Drukarni Gutenberg – format netto, spady, znaczniki cięcia, przestrzenie barw (RGB/CMYK/kolory dodatkowe), strefę bezpieczeństwa 3 mm, ramki 5 mm i bigi. Używaj, gdy klient przesyła projekt w PDF (także eksport z Canvy) albo pyta, czy jego PDF jest dobrze przygotowany.
---

# Sprawdzanie PDF do druku (Drukarnia Gutenberg)

Twoje zadanie: ocenić, czy PDF klienta jest gotowy do druku, i wyjaśnić klientowi prostym
językiem, co ewentualnie poprawić. **Nie poprawiasz plików klienta** – drukarnia nie ingeruje
w pliki bez wyraźnej prośby.

Zasady drukarni (spady 2,5 mm, tekst min. 3 mm od cięcia i bigu, ramki min. 5 mm, produkty
składane jako rozkładówki) są w `../margin-check/rules.yaml` – ten sam plik co dla obrazów.

## Krok 1. Ustal produkt

PDF zna swój rozmiar w mm, ale marginesy ocenia się względem produktu (np. „ulotka A5”,
„wizytówka 90×50”, „A4 składana do DL”). Jeśli klient nie podał produktu, uruchom
sprawdzenie bez `--product` – raport poda format netto i produkty, do których pasuje.
Wtedy zapytaj klienta albo wybierz produkt, jeśli wynika jednoznacznie z rozmowy.

```bash
python scripts/check_pdf.py --list-products
```

Format spoza listy: `--trim SZERxWYS` (mm), bigi: `--folds 99,198` (mm od lewej).

## Krok 2. Uruchom sprawdzenie

```bash
python scripts/check_pdf.py <plik.pdf> --product <id> --preview <katalog> [--json]
```

Dla każdej strony skrypt:
- czyta TrimBox / BleedBox / MediaBox: format netto, spad z każdej strony, znaczniki cięcia
  (`pdf_boxes.py`),
- zbiera przestrzenie barw faktycznie rysowanych zdjęć i grafiki: RGB, CMYK, kolory
  dodatkowe (`pdf_colors.py`); znaczniki cięcia z Canvy (kolor „All”) nie są liczone,
- rasteryzuje stronę w obszarze netto + spad (bez znaczników) i sprawdza spady, strefę 3 mm,
  ramki i bigi tym samym silnikiem co pliki graficzne (`pdf_margins.py`),
- zapisuje podgląd `strona_N_podglad.png`: czerwona = cięcie, zielona = strefa 3 mm,
  pomarańczowa = 5 mm, niebieska = big; problemy w ramkach.

Kody wyjścia: 0 OK, 1 ostrzeżenia lub do weryfikacji, 2 błędy, 3 nie da się sprawdzić
(brak pliku, uszkodzony PDF, PDF z hasłem).

### Najważniejsze kody wyników

| Kod | Znaczenie | Co powiedzieć klientowi |
|---|---|---|
| `FORMAT_MISMATCH` | format netto ≠ produkt | podać właściwy format (np. A5 = 148×210 mm) |
| `NO_BLEED_CONTENT_AT_EDGE` | tło do krawędzi, brak spadów | dodać 2,5 mm spadu z każdej strony |
| `BLEED_NOT_FILLED` | spad jest, ale biały | przedłużyć tło/grafikę na spad |
| `BLEED_SIZE` | spad mniejszy niż 2,5 mm | ustawić spad 2,5 mm |
| `ELEMENT_IN_SAFE_ZONE` | element bliżej niż 3 mm od cięcia | przesunąć tekst/logo do środka |
| `FRAME_TOO_CLOSE` | ramka bliżej niż 5 mm | odsunąć ramkę na min. 5 mm |
| `ELEMENT_NEAR_FOLD` | tekst przy bigu | odsunąć min. 3 mm od zgięcia |
| `SPOT_COLOR` | kolor dodatkowy (np. Gold) | ustalić, czy to warstwa do uszlachetnienia |
| `RGB` | zdjęcia/grafika w RGB | INFO; przy Canvie: eksport „PDF do druku” (CMYK) |
| `TRIMBOX_MISSING` | brak TrimBox, przyjęto spad z rozmiaru | zwykle OK, bez informowania klienta |

## Krok 3. Zweryfikuj wzrokowo i odpowiedz klientowi

1. **Zawsze obejrzyj podgląd** przy wynikach `SPRAWDŹ` i `OSTRZEŻENIE`. Skrypt mierzy piksele
   i nie wie, co jest tekstem, a co tłem – Twoja ocena rozstrzyga.
2. Odpowiedz po polsku, bez żargonu. Najpierw wynik (gotowe / do poprawy), potem konkretne
   poprawki z miejscem i liczbą („numer telefonu jest ok. 1,5 mm od lewej krawędzi – przesuń go
   min. 3 mm do środka”).
3. Przy błędach spadów wyjaśnij krótko *dlaczego*: przy cięciu mogą wystąpić przesunięcia
   1–2 mm, więc bez spadu zostaje biała linia.
4. Plik z Canvy z błędami spadów: poproś o eksport „PDF do druku (CMYK)” z zaznaczonym
   „Znaczniki przycięcia i spady” albo o link do współpracy z edycją.
5. PDF z hasłem (kod 3): poproś o plik bez zabezpieczenia.
6. Nie strasz informacjami `INFO` – wspominaj o nich tylko, gdy są przydatne.

## Ograniczenia – uwzględnij w ocenie

- **Tekst 2,5–3 mm od cięcia może nie zostać wykryty**, a odległość poniżej ok. 1,5 mm
  jest podawana jako ~0,4 mm. Przy elementach blisko krawędzi oceń podgląd sam.
- Rozdzielczości zdjęć w PDF skrypt jeszcze nie sprawdza – `render_dpi` to rozdzielczość
  analizy, nie zdjęć. Przy wizytówkach (600 dpi) i zdjęciach zapytaj o źródło, jeśli podgląd
  wygląda nieostro.
- Wzory (pattern) i przezroczystości nie są rozkładane na kolory – kod `COLOR_UNRECOGNISED`.
- Analiza zakłada biały papier; przy papierach kolorowych i tonerach specjalnych wyniki
  traktuj orientacyjnie.
- Duże formaty (banery, płótna, plakaty > A3) nie mają jeszcze reguł drukarni.
