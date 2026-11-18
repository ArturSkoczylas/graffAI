# Szkic AI – rozszerzenie Thunderbirda

Przycisk w widoku otwartej wiadomości ("Wygeneruj szkic odpowiedzi (AI)"). Klik wysyła surową
treść wiadomości do lokalnego [`harness`](../harness/) (musi już działać – patrz
[`../harness/README.md`](../harness/README.md)), a wygenerowany szkic ląduje w folderze Szkice
tej samej skrzynki, tak jak wcześniej.

## Instalacja (tymczasowa, do rozwoju)

1. `Narzędzia → Debugowanie dodatków` (`about:debugging`) → *Ten Thunderbird* → *Wczytaj
   tymczasowy dodatek* → wybierz `manifest.json` z tego katalogu.
2. Dodatek zniknie po restarcie Thunderbirda – wczytaj go ponownie po każdej zmianie kodu
   (szybsze niż pakowanie `.xpi` przy każdej edycji).

## Instalacja na trwałe

Thunderbird, w przeciwieństwie do Firefoksa, nie wymaga podpisywania dodatków przez AMO:

```bash
cd thunderbird-extension
zip -r ../szkic-ai.xpi . -x README.md
```

Potem w Thunderbirdzie: *Dodatki i Motywy* → ikona koła zębatego → *Zainstaluj dodatek z pliku*
→ wskaż `szkic-ai.xpi`. Zostaje po restarcie.

## Ustawienia

*Dodatki i Motywy → Szkic AI → Opcje* – adres backendu, domyślnie `http://127.0.0.1:8765/draft`
(musi się zgadzać z `API_PORT` w `.env` harnessu).

## Test end-to-end

1. Harness działa (`docker compose up -d` w głównym katalogu repo, `docker compose logs -f`
   bez błędów).
2. Otwórz prawdziwą wiadomość w Thunderbirdzie, kliknij przycisk.
3. Plakietka na przycisku: `...` (w trakcie) → `OK` (sukces, znika po chwili) albo `!`
   (błąd – treść w powiadomieniu systemowym).
4. Sprawdź folder Szkiców – powinien być nowy szkic z banerem
   `[SZKIC WYGENEROWANY PRZEZ AI — SPRAWDŹ PRZED WYSŁANIEM]`.

### Ścieżki błędów do sprawdzenia

- Harness nie działa → `fetch` się nie powiedzie, powiadomienie z błędem sieci.
- Wiadomość tylko HTML (bez `text/plain`) → harness i tak sobie radzi
  (`mailbox.extract_plain_text` zdziera tagi), ale warto to przetestować na realnej wiadomości.
- Wiadomość z załącznikiem PDF/obrazkiem → ignorowany, tak jak dotychczas (brak jeszcze
  integracji z `pdf-check`/`margin-check`).
