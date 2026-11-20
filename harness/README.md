# harness

Lokalny serwer HTTP, który na żądanie (`POST /draft`, surowy e-mail) przygotowuje **szkic**
odpowiedzi i zapisuje go w folderze Szkice tej samej skrzynki IMAP – nigdy nie wysyła niczego
sam. Wywołującym jest przycisk w rozszerzeniu Thunderbirda (`thunderbird-extension/`) – klik na
otwartej wiadomości wysyła jej surową treść (`messenger.messages.getRaw()`) do tego serwera.
Opis wewnętrznej struktury i przepływu danych: [ARCHITECTURE.md](ARCHITECTURE.md).

## Bezpieczeństwo

- Nic nie jest wysyłane automatycznie – `create_draft` zapisuje do Szkiców (IMAP APPEND,
  flaga `\Draft`), pracownik przegląda i wysyła ręcznie.
- Treści klienta nigdy nie trafiają do kodu jako polecenia – prompt wyraźnie oznacza je
  jako dane (`<wiadomosc>...</wiadomosc>`).
- Agent może uruchamiać kod (`run_skill_script`), ale tylko konkretne, zaszyte w kodzie skrypty
  skilli (`wycena.py`, `canva_link.py` – lista w `harness/src/agent/run_script.py`), przez
  `subprocess.run([...], shell=False)` – argumenty idą jako argv, nie przez shell, więc nie ma
  wstrzyknięcia komend. Model nie może wskazać dowolnej ścieżki ani uruchomić czegoś poza tą
  listą. `wycena.py` woła prawdziwe API wycen (`GRAFFAI_WYCENA_URL`) – to realny efekt
  zewnętrzny (zapytanie o cenę), nie tylko odczyt.
- Nic na `POST /draft` nie wymaga uwierzytelniania – bezpieczeństwo opiera się wyłącznie na
  tym, że port nie jest wystawiony na sieć. W Dockerze to robi `ports: ["127.0.0.1:8765:8765"]`
  w `docker-compose.yml` (publikuje port tylko na loopbacku hosta) – `API_HOST` w kontenerze
  musi mieć wartość `0.0.0.0` (Docker przekazuje ruch na interfejs kontenera, nie na jego
  własny loopback), to nie jest dziura, to jest wymagane do działania. **Jeśli uruchamiasz
  `main.py` bez Dockera, zostaw `API_HOST=127.0.0.1` (domyślne) – wtedy to on jest granicą.**

## Szybki start

```bash
cp .env.example .env    # w głównym katalogu repo
# ... wypełnij .env, patrz sekcje niżej ...
docker compose up --build -d
docker compose logs -f
```

Potem zainstaluj rozszerzenie Thunderbirda – patrz
[`../thunderbird-extension/README.md`](../thunderbird-extension/README.md).

## Zmienne środowiskowe

| Zmienna | Wymagana | Domyślna | Opis |
|---|---|---|---|
| `IMAP_HOST` | ✅ | – | Serwer IMAP (to samo, co masz w Thunderbirdzie) |
| `IMAP_PORT` | | `993` | Port IMAP (SSL) |
| `IMAP_USER` | ✅ | – | Pełny adres e-mail |
| `IMAP_PASSWORD` | ✅ | – | Hasło zwykłe albo hasło aplikacji (patrz niżej) |
| `IMAP_USE_SSL` | | `true` | |
| `IMAP_DRAFTS_FOLDER` | | `Drafts` | **Prawie nigdy nie jest to poprawna wartość dla Gmaila** – patrz niżej |
| `API_HOST` | | `127.0.0.1` | Zostaw tak jak jest – patrz sekcja Bezpieczeństwo |
| `API_PORT` | | `8765` | Jeśli zmienisz, zaktualizuj też `ports:` w `docker-compose.yml` i adres w ustawieniach rozszerzenia |
| `AI_PROVIDER` | | `claude` | obecnie tylko `claude` zaimplementowany |
| `AI_MODEL` | | `claude-sonnet-5-5` | |
| `AI_API_KEY` | ✅ | – | klucz z console.anthropic.com |
| `AI_MAX_TOKENS` | | `3000` | |
| `FROM_ADDRESS` | | = `IMAP_USER` | ustaw, jeśli odpowiedzi mają wychodzić z innego adresu/aliasu |

## Konfiguracja dla popularnych dostawców

### Gmail

```
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_DRAFTS_FOLDER=[Gmail]/Drafts    # patrz UWAGA niżej – to zależy od języka konta
```

1. Włącz dostęp IMAP: *Gmail → Ustawienia (ikona koła zębatego) → Zobacz wszystkie ustawienia
   → Przekazywanie i POP/IMAP → Włącz IMAP → Zapisz zmiany.*
2. Google od 2022 roku **nie pozwala na logowanie IMAP zwykłym hasłem konta** – niezależnie
   od tego, czy masz włączone 2FA. Musisz użyć hasła aplikacji, co wymaga najpierw
   włączenia weryfikacji dwuetapowej:
   - Włącz 2-Step Verification: `myaccount.google.com/security`.
   - Wygeneruj hasło aplikacji: `myaccount.google.com/apppasswords` → wybierz "Mail" (albo
     "Other", nazwij np. "mail-harness") → Google pokaże 16-znakowe hasło. Wpisz je jako
     `IMAP_PASSWORD` (ze spacjami czy bez – obie formy działają).
3. **UWAGA – folder Szkiców zależy od języka interfejsu konta**, nie jest to zawsze
   `[Gmail]/Drafts`. Np. dla konta z polskim interfejsem to `[Gmail]/Wersje robocze`.
   Sprawdź realną nazwę poleceniem z sekcji [„Jak znaleźć nazwę folderu Szkice”](#jak-znaleźć-nazwę-folderu-szkice) – **zrób to zawsze przy konfiguracji Gmaila**, zgadywanie
   kończy się błędem `[TRYCREATE] Folder doesn't exist`.

### Microsoft 365 / Outlook.com / Exchange Online

```
IMAP_HOST=outlook.office365.com
IMAP_PORT=993
IMAP_DRAFTS_FOLDER=Drafts
```

Tu jest realne ograniczenie, nie tylko konfiguracyjne: Microsoft od 2022 wygasza
**uwierzytelnianie podstawowe (login+hasło) dla IMAP** w Exchange Online – dla większości
kont firmowych/szkolnych jest już całkowicie zablokowane i wymaga OAuth2, czego ten harness
nie implementuje (patrz [ARCHITECTURE.md](ARCHITECTURE.md), `BaseProvider`/IMAP to osobna
warstwa – OAuth2 dla IMAP wymagałby nowej ścieżki logowania w `mailbox.connect`).

- Dla kont **prywatnych** (outlook.com/hotmail.com, nie firmowych) logowanie hasłem
  aplikacji może wciąż działać: włącz weryfikację dwuetapową w ustawieniach konta
  Microsoft, potem wygeneruj hasło aplikacji w sekcji bezpieczeństwa konta (ścieżka w UI
  Microsoft zmienia się często – szukaj "App passwords" / "Hasła aplikacji" w
  `account.microsoft.com/security`).
- Dla kont **firmowych/szkolnych (Microsoft 365)** – zapytaj administratora IT, czy IMAP
  z uwierzytelnianiem podstawowym jest w ogóle włączony dla organizacji. Jeśli nie, ten
  harness nie będzie w stanie się zalogować, niezależnie od hasła.

### Inny serwer IMAP (firmowa skrzynka, hosting, Dovecot itp.)

Użyj tych samych danych, które masz skonfigurowane w Thunderbirdzie (*Ustawienia konta →
Ustawienia serwera*). Nazwa folderu Szkiców bywa `Drafts`, `INBOX.Drafts` albo coś
niestandardowego – sprawdź poleceniem poniżej, nie zgaduj.

## Jak znaleźć nazwę folderu Szkice

Nie zgaduj – wylistuj prawdziwe foldery konta (wymaga, żeby `.env` było już wypełnione
poprawnym hostem/loginem/hasłem; nic nie modyfikuje skrzynki):

```bash
docker compose run --rm mail-harness python3 -c "
import os, imapclient
c = imapclient.IMAPClient(os.environ['IMAP_HOST'], port=int(os.environ.get('IMAP_PORT', 993)), ssl=True)
c.login(os.environ['IMAP_USER'], os.environ['IMAP_PASSWORD'])
for flags, delimiter, name in c.list_folders():
    print(name, '|', flags)
c.logout()
"
```

Szukaj folderu z flagą `\Drafts` w wyniku – to jest właściwa wartość dla
`IMAP_DRAFTS_FOLDER`, niezależnie od tego, jak się nazywa w interfejsie.

## Testowanie

1. `docker compose logs -f` – sprawdź, czy serwer wystartował i nasłuchuje na `API_PORT`.
2. `curl -X POST localhost:8765/draft --data-binary @sample.eml` z przykładowym plikiem `.eml`
   – albo kliknij przycisk w Thunderbirdzie na prawdziwej wiadomości.
3. Sprawdź folder Szkiców w Thunderbirdzie – powinien tam być nowy szkic z banerem
   `[SZKIC WYGENEROWANY PRZEZ AI — SPRAWDŹ PRZED WYSŁANIEM]` na początku.

## Rozwiązywanie problemów

| Błąd w logach / odpowiedzi | Przyczyna | Rozwiązanie |
|---|---|---|
| `[AUTHENTICATIONFAILED] Invalid credentials` | Zwykłe hasło konta tam, gdzie dostawca wymaga hasła aplikacji (Gmail: zawsze; Microsoft: zwykle) | Włącz 2FA i wygeneruj hasło aplikacji – patrz sekcja dostawcy wyżej |
| `[TRYCREATE] Folder doesn't exist` przy zapisie szkicu | `IMAP_DRAFTS_FOLDER` nie zgadza się z rzeczywistą nazwą folderu | Wylistuj foldery (sekcja wyżej), ustaw poprawną wartość, `docker compose up -d --force-recreate` |
| Przycisk w Thunderbirdzie nic nie robi / błąd sieci | Kontener nie działa albo `API_PORT` w rozszerzeniu nie zgadza się z `docker-compose.yml` | `docker compose ps`, sprawdź port w ustawieniach rozszerzenia |
| Odpowiedź `500` z `/draft` | Zwykle błąd modelu albo IMAP przy zapisie – treść błędu jest w polu `message` odpowiedzi i w logach kontenera | `docker compose logs -f`, napraw przyczynę, kliknij przycisk jeszcze raz |

## Czego nie robi (jeszcze)

- Nie analizuje załączników (np. plików do druku) – to zadanie na przyszłość dla
  `skills/margin-check` / `skills/pdf-check`, osobne narzędzie dla agenta.
- Działa tylko z Claude (`AnthropicProvider`). `AI_PROVIDER=openai` jest rozpoznawane,
  ale zgłasza `NotImplementedError` – dodanie `OpenAIProvider` nie wymaga zmian
  w `agent_loop.py` ani `api/server.py`, tylko nowej klasy w `harness/src/agent/providers/`.
- Loguje się tylko login+hasłem (IMAP Basic Auth) – żadnego OAuth2. To realnie wyklucza
  większość kont Microsoft 365 firmowych/szkolnych (patrz sekcja Microsoft wyżej).
- Nie obserwuje skrzynki automatycznie – to świadoma zmiana względem wcześniejszej wersji
  (IDLE/poll watcher); każdy szkic powstaje tylko na kliknięcie przycisku w Thunderbirdzie.
