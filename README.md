# forum-rss — MobilMania fórum → RSS

Denní scraper vybraných vláken phpBB fóra, výstupem je `feed.xml` použitelný v jakékoli RSS čtečce nebo v rss-digest pipeline.

## Setup (jednorázově)

1. Vytvoř nový GitHub repo (klidně privátní) a nahraj tam tyhle soubory.
2. V `config.yml` doplň svých ~10 vláken — `id` je parametr `t` z URL vlákna
   (`viewtopic.php?f=1&t=1329158` → id `1329158`).
3. V repu: **Settings → Actions → General → Workflow permissions** →
   zaškrtni **Read and write permissions** (jinak push feedu selže).
4. První spuštění udělej ručně: **Actions → Denní scrape fóra → Run workflow**.
   Pak už to jede samo každý den ráno.

## URL feedu

- Privátní repo: `feed.xml` si stahuj přes API s tokenem, nebo repo nech veřejné.
- Veřejné repo (nejjednodušší):
  `https://raw.githubusercontent.com/<user>/<repo>/main/feed.xml`
  — tuhle URL přidej do RSS čtečky / rss-digest configu.

## Jak to funguje

- `state.json` — poslední zpracované post ID pro každé vlákno (stahují se jen nové příspěvky)
- `items.json` — rolling zásobník posledních N položek (feed nezmizí, ani když den nic nepřibude)
- `feed.xml` — vygenerovaný RSS

První běh vezme jen poslední ~2 stránky každého vlákna (nastavitelné přes `pages_back`), nestahuje celou historii.

## Poznámky

- Mezi requesty je pauza (`delay_seconds`), běží to 1× denně — buď k serveru slušný a nezkracuj to.
- Pokud fórum změní šablonu a přestanou se parsovat příspěvky, uprav selektory v `parse_posts()` (`div.post`, `.author`, `div.content`).
