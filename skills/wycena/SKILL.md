---
name: wycena
description: Wyciąga z maila klienta dane zamówienia (produkty, format, papier, nakład, druk, uszlachetnienia, książki) i wycenia je w systemie wycen drukarni przez API. Używaj, gdy pracownik prosi o wycenę zamówienia z wiadomości klienta.
---

# Wycena zamówienia z maila (Drukarnia Gutenberg)

Zadanie: z wiadomości klienta przygotować zamówienie w formacie systemu wycen, wycenić je
skryptem i oddać pracownikowi **podsumowanie z ceną, założeniami i pytaniami do klienta**.
Ceny liczy wyłącznie system wycen – nigdy nie licz ani nie szacuj ceny sam.

Wymaga działającej aplikacji wycen (adres w `GRAFFAI_WYCENA_URL`, domyślnie
`http://localhost:5001/api`). Sprawdzenie: `python scripts/wycena.py --papers`.

## Krok 1. Rozpoznaj pozycje

Każdy osobny produkt (inny format, papier, nakład lub wykończenie) to osobna pozycja.
Np. „zaproszenia + winietki + plan stołów” = 3 pozycje. Te same zaproszenia w dwóch
wersjach kolorystycznych po 50 szt. to jedna pozycja ze 100 szt., chyba że różnią się papierem
lub wykończeniem.

**Poza wyceną** (nie wysyłaj do API, wpisz do `poza_wycena`): obrazy na płótnie i fototapety
(zamawiane przez sklep internetowy), banery i druk wielkoformatowy, grawer, projekt graficzny,
fotoksiążki i fotoalbumy, naklejki wycinane z folii.

## Krok 2. Wypełnij pola – produkty jednokartkowe i składane (`type: "plano"`)

| Pole | Jak wypełnić |
|---|---|
| `nazwa` | krótko: „zaproszenie”, „winietka”, „wizytówka”, „ulotka A5” |
| `format` | ISO (A4, A5, A6, B6, C6, DL nie – DL podaj jako `99x210`) albo `szerokośćxwysokość` w **mm**, np. `100x150`. cm → mm (14×14 cm = `140x140`). **Produkt składany: format po rozłożeniu** (zaproszenie 140×140 składane = `280x140`; A5 składane do A6 = `A5`). |
| `papier` | **dokładnie** nazwa z listy `--papers`. „Kreda”, „zwykły kredowy” → kreda mat o gramaturze z maila (domyślnie 300g dla zaproszeń i wizytówek, 170g dla ulotek, 135g dla plakatów – to założenie). Opis papieru ozdobnego dopasuj do najbliższej nazwy i zapisz to jako założenie. |
| `naklad` | liczba sztuk; brak = **pytanie**, nie zgaduj |
| `druk` | `4+0` jednostronny, `4+4` dwustronny („przód i tył”, „dwustronne” → `4+4`). Brak informacji: `4+0` + założenie. |
| `laminowanie` | `-` brak, `1+0` jednostronne, `1+1` dwustronne. Folia matowa/błyszcząca/soft touch = laminowanie. |
| `zlocenie` | `-`, `1+0`, `1+1`. Złocenie, srebrzenie, folia złota/srebrna, lakier UV wybiórczy = złocenie. |
| `personalizacja` | `""` brak; zaproszenia „z wpisanymi gośćmi”, winietki z nazwiskami = `programik` (dwustronna: `programik_duplex`); ręczna = `manual`; kolorem specjalnym = `special_color` |
| `iecho` | `true` dla wydruków wycinanych po obrysie / nietypowy kształt; `complex_patterns_enabled: true`, jeśli kształt jest skomplikowany |
| `ricoh_special_color` | `true` dla druku tonerem białym, złotym lub srebrnym (np. na kolorowym papierze) |
| `cutter` | zostaw `false` (znaczenie do potwierdzenia z drukarnią) |
| `wymiar_arkusza`, `margines_bok`, `margines_gora`, `spad` | zawsze `"SRA3"`, `"5"`, `"5"`, `"2.5"` |

## Krok 3. Książki, broszury, katalogi

| Typ | Kiedy | Pola |
|---|---|---|
| `saddle_stitched_book` | broszura, katalog, zeszyt **zszywany** (8–72 str., wielokrotność 4) | `format` (A4/A5/A6/DL/210x210 lub `{"width","height"}`), `orientacja` (pionowa/pozioma), `liczba_stron` (z okładką), `druk_okladki`, `papier_okladki`, `wykonczenie_okladki` (brak / folią matową / folią połysk / folią soft skin), `druk_srodka` (4+4 lub 1+1), `papier_srodka` |
| `softcover_book` | książka / katalog **klejony**, miękka oprawa | `krotszy_bok`, `dluzszy_bok` (mm), `liczba_stron` (z okładką), `druk_okladki`, `papier_okladki`, `wykonczenie_okladki` (brak / folią matową antyzarysowaniową jednostronnie / folią połysk jednostronnie / folią soft skin jednostronnie), `druk_srodka`, `papier_srodka` |
| `hardcover_book` | twarda oprawa | `format` (A4/A5/A6/B5/B6/210x210), `liczba_stron_srodka` (bez okładki), `wykonczenie_okladki` (folią matową/połysk/soft skin jednostronnie), `kolor_wyklejki` (biały/czarny), `druk_srodka`, `papier_srodka` |

Każda książka ma też `nazwa`, `naklad`. **System nie wycenia jeszcze książek** – skrypt pokaże je
bez ceny, a suma zamówienia z książką będzie nieznana. Zaznacz to pracownikowi.

## Krok 4. Pola całego zamówienia

| Pole | Wartość |
|---|---|
| `order_group` | `A` – typowe zaproszenia jednokartkowe lub składane; `B` – kilka różnych produktów (np. zaproszenia + wkładki), **domyślnie**; `C` – zamówienie wymagające dużo pracy |
| `wedding_order` | `true` dla zamówień ślubnych (zaproszenia, winietki, papeteria na wesele) |
| `shipping_enabled` | `true`, jeśli klient chce wysyłkę kurierem |
| `confection_quantity` | liczba sztuk do konfekcjonowania (składanie, wkładanie do kopert), jeśli klient o to prosi; inaczej 0 |
| `matrix_price` | `0` – koszt matrycy ustala pracownik |

## Krok 5. Zapisz plik zamówienia i wyceń

Zapisz plik JSON (poza repo, np. `out/wycena-<nazwa>.json`):

```json
{
  "zamowienie": {"products": [ ... ], "order_group": "B", "wedding_order": false,
                 "shipping_enabled": false, "confection_quantity": 0, "matrix_price": "0"},
  "zalozenia": ["Druk jednostronny – klient nie napisał", "Papier: kreda mat 300g"],
  "pytania": ["Ile sztuk winietek?"],
  "poza_wycena": ["Obraz na płótnie 50×70 – zamówienie przez sklep internetowy"]
}
```

Pozycje z brakami (np. bez nakładu) **nie trafiają** do `products` – wpisz je do `pytania`.
Potem:

```bash
python scripts/wycena.py out/wycena-<nazwa>.json            # podsumowanie dla pracownika
python scripts/wycena.py out/wycena-<nazwa>.json --json     # pełna odpowiedź API
```

Kody wyjścia: 0 wycenione, 1 wycenione częściowo (książki bez ceny, pytania do klienta),
2 błąd danych (HTTP 422 – popraw pola wg komunikatu i uruchom ponownie), 3 brak połączenia z API.

## Krok 6. Odpowiedz pracownikowi

Podaj: cenę końcową (`Razem`), ceny pozycji, **wszystkie założenia** (pracownik musi je
zweryfikować przed wysłaniem ceny klientowi), pytania do klienta i pozycje poza wyceną.
Nie wysyłaj klientowi ceny bez akceptacji pracownika. Przy błędzie 422 popraw dane – nie
zmieniaj wartości „na siłę”, żeby wycena przeszła (np. nie podmieniaj papieru bez założenia).
