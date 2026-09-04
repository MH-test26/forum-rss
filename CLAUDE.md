# CLAUDE.md — forum-rss

Předávací technická dokumentace pro Claude Code. Popisuje repo `MH-test26/forum-rss`:
scraper vybraných vláken phpBB fór → `feed.xml`, který konzumuje RSS čtečka a `rss-digest` pipeline.

> **Před první změnou:** dokumentace vychází ze stavu při nasazení. Ověř si aktuální obsah
> `scraper.py` a `config.yml` v repu — mohly být mezitím ručně upravené (viz sekce *Ověřit při převzetí*).

---

## 1. Účel a kontext

- Sledovaná vlákna běží na phpBB fórech, kde je **nativní `feed.php` vypnutý** (vrací 404).
  Proto vlastní scraper místo přímého RSS.
- Repo je **veřejné záměrně** — feed se čte přes `raw.githubusercontent.com` bez tokenu.
- Výstupní URL feedu:
  `https://raw.githubusercontent.com/MH-test26/forum-rss/main/feed.xml`
- Sleduje se **14 vláken napříč dvěma doménami**:
  - `forum.mobilmania.zive.cz` — t = 1329158, 1335982, 1330727, 1326917, 1333379, 1341165
  - `forum.finexpert.e15.cz` — t = 1200034, 1142003, 1131529, 301647, 1120912, 1078058, 1256188, 1239073
- Provozní režim je vědomě konzervativní: **1× denně**, pauza mezi requesty,
  vlastní User-Agent. **Nezvyšuj frekvenci cronu ani nesnižuj `delay_seconds`** —
  toto omezení je závazné, neobcházej ho ani při ladění.

---

## 2. Rychlý start

```bash
pip install -r requirements.txt
python scraper.py          # celý běh: scrape → state → items → feed.xml
```

Skript nemá CLI argumenty ani flagy — veškeré chování řídí `config.yml`.
Běh je idempotentní vůči již viděným příspěvkům (viz `state.json`).

Lokální test bez síťového provozu (doporučený způsob, jak ověřit změny v parsování):

```python
from bs4 import BeautifulSoup
import scraper
soup = BeautifulSoup(open("sample_page.html", encoding="utf-8").read(), "html.parser")
posts = scraper.parse_posts(soup, {"id": 1329158, "name": "Test"}, "https://forum.mobilmania.zive.cz")
print(scraper.find_last_start(soup), scraper.posts_per_page(soup), len(posts))
```

---

## 3. Struktura repa

```
forum-rss/
├── config.yml                  # vlákna + nastavení (jediné místo pro konfiguraci)
├── scraper.py                  # veškerá logika, ~250 řádků, bez tříd
├── requirements.txt            # requests, beautifulsoup4, feedgen, PyYAML
├── README.md                   # uživatelský setup
├── .github/workflows/daily.yml # cron 04:30 UTC + workflow_dispatch
├── state.json                  # generováno: poslední viděné post ID na vlákno
├── items.json                  # generováno: rolling zásobník položek feedu
└── feed.xml                    # generováno: výstupní RSS
```

`state.json`, `items.json` a `feed.xml` **jsou verzované** (commituje je workflow) — nejsou v `.gitignore`
a nesmí do něj přibýt, jinak by se při každém běhu resetovala paměť.

---

## 4. Datový tok

```
config.yml ──► scrape_thread()  ──► parse_posts()  ──► filtr podle state.json
                    │                                        │
              fetch poslední                            nové příspěvky
              N stránek vlákna                                │
                                                              ▼
                                     items.json (append, ořez na max_feed_items)
                                                              │
                                                              ▼
                                                build_feed() ──► feed.xml
                                                              │
                                                    git commit & push (Actions)
                                                              │
                                                              ▼
                                     raw.githubusercontent.com → rss-digest / čtečka
```

Klíčový návrhový záměr: **`items.json` je rolling buffer**, ne jen dnešní dávka. Feed se generuje
vždy z celého bufferu, takže ve dnech bez nových příspěvků feed nezmizí ani se nevyprázdní.

---

## 5. `config.yml` — schéma

```yaml
threads:
  - id: 1329158
    name: "MobilMania vlakno 1329158"          # jen popisek do titulku položky
    base_url: "https://forum.mobilmania.zive.cz"
  - id: 1200034
    name: "FinExpert vlakno 1200034"
    base_url: "https://forum.finexpert.e15.cz"

settings:
  pages_back: 2          # kolik posledních stránek vlákna kontrolovat
  delay_seconds: 4       # pauza mezi requesty — nesnižovat
  max_feed_items: 300    # velikost rolling bufferu (zvýšeno ze 150 kvůli 14 vláknům)
  feed_file: "feed.xml"
  state_file: "state.json"
  items_file: "items.json"

feed:
  title: "..."
  description: "..."
  language: "cs"
```

**Důležité:** `base_url` je **per-thread**, ne globální. Původní verze měla jeden globální `base_url`;
po přidání druhé domény se přesunul do jednotlivých položek `threads`. Když upravuješ `scraper.py`,
nepředpokládej `cfg["base_url"]` na kořenové úrovni.

`name` je čistě kosmetický — promítne se do titulku položek při dalším běhu scraperu.
Změna `name` neovlivní `state.json` ani už vygenerované položky v `items.json`.

---

## 6. `scraper.py` — funkce

| Funkce | Odpovědnost |
|---|---|
| `load_config()` | načte `config.yml` |
| `load_json()` / `save_json()` | perzistence stavu, UTF-8, `ensure_ascii=False` |
| `fetch(url, delay)` | GET + `BeautifulSoup`, chyby loguje a vrací `None` (běh nespadne), `time.sleep(delay)` ve `finally` |
| `find_last_start(soup)` | z `div.pagination a[href*='start=']` vytáhne nejvyšší `start=` → poslední stránka |
| `posts_per_page(soup)` | odhad kroku stránkování z pagination odkazů, fallback `40` |
| `parse_posts(soup, thread, base_url)` | extrakce příspěvků ze stránky |
| `scrape_thread(thread, cfg, last_seen)` | stáhne poslední `pages_back` stránek, vrátí jen `id > last_seen` |
| `build_feed(items, cfg)` | `feedgen` → RSS soubor |
| `main()` | orchestrace + ořez bufferu + zápis |

### Parsovací selektory (phpBB prosilver)

Tohle je nejkřehčí místo celého repa — při změně šablony fóra se opravuje tady:

- příspěvek: `div.post` s atributem `id="pNNNN"` → `post_id` z regexu `p(\d+)`
- autor: `.author strong, .author a.username, .author a.username-coloured`, fallback `"neznámý"`
- čas: `.author time[datetime]` přes `datetime.fromisoformat()`; fallback `datetime.now(timezone.utc)`
- obsah: `div.content` — do feedu jde **HTML** (`fe.content(..., type="CDATA")`), plain text se používá jen pro titulek (prvních 90 znaků)
- permalink: `{base_url}/viewtopic.php?p={pid}#p{pid}`

Příspěvek bez `div.content` nebo bez validního `id` se přeskočí.

### Řazení a identita

- **Post ID je jediný řadicí a dedup klíč.** Předpoklad: rostoucí ID = novější příspěvek.
  Čas z fóra se používá jen pro `pubDate` ve feedu, nikdy pro dedup.
- `build_feed()` řadí položky **vzestupně podle ID**, protože `feedgen` je do RSS zapisuje obráceně —
  výsledkem je nejnovější nahoře. Tohle nepřehazuj bez otestování výstupního XML.

---

## 7. Stavové soubory

### `state.json`
```json
{ "https://forum.mobilmania.zive.cz::1329158": 9001234 }
```
Klíč je **`base_url::thread_id`**, ne holé ID. Důvod: obě fóra mají vlastní číselné řady vláken
a mohla by kolidovat. Při refaktoru zachovej formát klíče, jinak scraper ztratí paměť a příště
naimportuje poslední 2 stránky všech vláken znovu jako „nové“.

### `items.json`
Pole objektů se stejnými klíči, jaké vrací `parse_posts()`:
`id`, `thread_id`, `thread_name`, `author`, `published` (ISO string), `link`, `title`, `html`.
V `main()` se ořezává na posledních `max_feed_items` položek podle ID.

---

## 8. GitHub Actions (`.github/workflows/daily.yml`)

- `schedule: cron "30 4 * * *"` (04:30 UTC = 6:30 CEST / 5:30 CET) + `workflow_dispatch`
- `permissions: contents: write` — v repu navíc musí být zapnuté
  **Settings → Actions → General → Workflow permissions → Read and write**, jinak push selže
- `concurrency: forum-scrape`, `cancel-in-progress: false`
- commit krok: `git add feed.xml state.json items.json`, commit jen když `git diff --staged` není prázdný

**Deprecation warningy v logu** (typu „Node.js 20 is deprecated, forced to run on Node.js 24“)
jsou kosmetické — workflow doběhne úspěšně. Nejde o chybu; případný upgrade `actions/checkout`
a `actions/setup-python` na novější major verze je volitelný úklid, ne fix.

---

## 9. Napojení na rss-digest

Feed konzumuje privátní repo `rss-digest`; konfigurace je na jeho straně.

Změna v `config.yml` (přidání/odebrání vlákna) **nevyžaduje** žádnou úpravu u konzumenta —
ten vidí jen jeden agregovaný feed. Zásah na jeho straně je nutný jen při změně URL nebo názvu větve.

---

## 10. Známé pitfally

1. **Ztráta `state.json`** = 14 vláken × poslední 2 stránky se naimportuje jako nové → jednorázově obří feed.
   Před destruktivními změnami stavu si soubor zazálohuj.
2. **`pages_back: 2`** je pojistka proti přetečení stránky přes noc. Vlákno, kde za den přibude
   víc než ~2 stránky příspěvků, o starší novinky přijde. Pokud se to stane, zvyš `pages_back`,
   ne frekvenci cronu.
3. **`posts_per_page()` fallback 40** — pokud vlákno vejde na jednu stránku (žádná pagination),
   `find_last_start()` vrátí 0 a stahuje se jen první stránka. To je správně, ne bug.
4. **Fóra blokují automatizovaný fetch** — z Claude Code prostředí se stránka nemusí načíst.
   Pro ladění parsování si nech poslat/uložit HTML jedné stránky a testuj offline.
5. **Změna šablony fóra** se projeví jako „0 příspěvků načteno“ v logu, ne jako pád.
   Diagnostika: uložit HTML, zkontrolovat `div.post` / `.author` / `div.content`.
6. **Git historie repa roste** — `items.json` a `feed.xml` se commitují denně. Pro tenhle rozsah
   je to neškodné, ale nepřidávej do commitu další velké generované soubory.

---

## 11. Typické úkoly

| Úkol | Postup |
|---|---|
| Přidat vlákno | do `config.yml` → `threads` přidat `id` (parametr `t` z URL), `name`, `base_url` |
| Přejmenovat vlákno | upravit `name` v `config.yml`; projeví se u nových položek po dalším běhu |
| Odebrat vlákno | smazat z `config.yml`; osiřelý klíč ve `state.json` můžeš nechat, nevadí |
| Vyčistit feed | smazat `items.json` + `feed.xml`, `state.json` **nechat** → feed se naplní postupně novými posty |
| Reset od nuly | smazat všechny tři generované soubory a spustit workflow ručně |
| Ruční běh | Actions → *Denní scrape fóra* → Run workflow |
| Filtrování podle autora | zatím neimplementováno; přirozené místo je filtr v `scrape_thread()` nad výstupem `parse_posts()` |

---

## 12. Ověřit při převzetí

- Aktuální hodnoty v `config.yml` (názvy vláken mohly být ručně přepsané ze zástupných `... vlakno <id>`).
- Zda `scraper.py` už nemá další ruční úpravy proti popisu výše — zejména podpis
  `scrape_thread()` a způsob čtení `base_url`.
- Zda jsou v `state.json` klíče ve formátu `doména::id` u **všech** vláken.
- Poslední úspěšný běh workflow a velikost `items.json` vůči `max_feed_items`.
