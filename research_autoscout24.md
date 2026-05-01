# Парсинг autoscout24.ru + LLM-скоринг + Google Sheets

Стек по выбору пользователя: **Python**, **Google Sheets API**, **Claude Haiku 4.5** или **GPT-4.1 nano**.

---

## TL;DR (что делать)

1. **Парсер** — `curl_cffi` (TLS-fingerprint Chrome) + извлечение `__NEXT_DATA__` JSON со страниц `/lst` и `/offers/{slug}`. Если начнут прилетать 403 от Akamai — переезжать на `camoufox` (headless Firefox с патченным fingerprint) + residential EU-прокси.
2. **LLM-скоринг** — `instructor` + Pydantic-модель, structured output. Модель: **GPT-4.1 nano** (батч ~$0.04 на 1000 объявлений) или **Claude Haiku 4.5** (~$0.85 за 1000, но качество скоринга и tool use заметно выше).
3. **Хранилище** — Google Sheets через `gspread` + `gspread-formatting` для условного выделения по score. Дедуп по `listing_id`, отдельный лист `price_history` для трекинга цен.
4. **Оркестрация** — cron или systemd timer на Hetzner CAX11 (€3.49/мес, EU IP — нет блокировок Anthropic/OpenAI).
5. **Уведомления** — Telegram Bot API при `score >= 8`.

Итого месяц: **~$5–7** (Hetzner + LLM батч).

---

## 1. autoscout24.ru — статус и что парсить

- Сайт **жив** (май 2026), отдельный домен (не редирект), хостится на AWS, ~157K визитов/мес. Это русскоязычная оболочка над общей базой autoscout24, объявления европейские в EUR. Если нужен внутренний рынок РФ — это **не тот** сайт, смотри `auto.ru` / `avito.ru/transport` / `drom.ru`.
- Публичного API нет. Listing Creation API — только для дилеров. Партнёрский API требует договора.
- Antibot: **Akamai Bot Manager** (не Cloudflare). robots.txt запрещает `/lst?` и GraphQL endpoints, но фактическое чтение страниц HTML работает.
- Рендеринг: **Next.js SSR**. На каждой странице есть `<script id="__NEXT_DATA__" type="application/json">` с полным JSON-дампом данных. Парсить нужно **именно его**, а не CSS-селекторы (классы Next.js меняются между деплоями).

### Ключевые пути в `__NEXT_DATA__`

```python
# страница поиска /lst?...
data["props"]["pageProps"]["listings"]          # массив ~20 объявлений

# страница объявления /offers/{slug}
data["props"]["pageProps"]["listingDetails"]    # 20+ полей: марка, модель, год,
                                                # пробег, мощность, оборудование,
                                                # CO2, контакты продавца и т.д.
```

### URL-параметры фильтра `/lst`

```
mmvmk0=BRAND_ID        # марка
mmvmd0=MODEL_ID        # модель
fregfrom=2018          # год от
fregto=2024            # год до
pricefrom=5000         # EUR от
priceto=30000
kmfrom=0
kmto=150000
cy=D,A,CH              # страны (D=Germany, A=Austria, CH=Switzerland)
sort=age               # age = по дате появления (для daily diff)
page=1                 # 1..N, по 20 шт.
```

Самый надёжный способ собрать корректный URL — выставить фильтры руками на сайте и скопировать query string.

---

## 2. Парсер на Python

### Базовый стек (MVP)

```python
# pyproject / requirements
# curl_cffi    — TLS/HTTP2 fingerprint Chrome, ~80% success rate против Akamai без JS-челленджа
# orjson       — быстрее json для большого __NEXT_DATA__
# selectolax   — на случай парсинга HTML (в 30x быстрее BeautifulSoup)
# tenacity     — retry с экспоненциальным backoff
```

```python
from curl_cffi import requests as cureq
from selectolax.parser import HTMLParser
import orjson

def fetch_page(url: str, session: cureq.Session) -> dict:
    r = session.get(url, impersonate="chrome124", timeout=30)
    r.raise_for_status()
    tree = HTMLParser(r.text)
    node = tree.css_first('script#__NEXT_DATA__')
    return orjson.loads(node.text())

def iter_listings(query_url: str, max_pages: int = 20):
    s = cureq.Session()
    for page in range(1, max_pages + 1):
        data = fetch_page(f"{query_url}&page={page}", s)
        listings = data["props"]["pageProps"].get("listings") or []
        if not listings:
            break
        yield from listings
```

### Если Akamai начнёт блочить

1. Добавить **residential proxies EU** (Bright Data ~$8.4/GB, IPRoyal дешевле).
2. Перейти на **camoufox** (`pip install camoufox && python -m camoufox fetch`) — headless Firefox с патченным C++-уровневым fingerprint, ~92% success против Akamai.
3. Сохранять и переиспользовать cookie `_abck` и `ak_bmsc` в рамках сессии (привязаны к IP — ротировать только между сессиями, не внутри).
4. Задержки 2–8 сек между запросами, рандомизация.

### Альтернатива: готовый Apify-актор

`apify/blackfalcondata~autoscout24-scraper` — платишь за compute, ~$0.25–1 за 1000 результатов, ничего не настраиваешь. Хорошо как запасной план или для одноразового бэкфилла.

---

## 3. LLM-скоринг

### Выбор модели

| | **GPT-4.1 nano** | **Claude Haiku 4.5** |
|---|---|---|
| Цена input (батч) | $0.05 / MTok | $0.50 / MTok |
| Cache hit | $0.025 | $0.10 |
| Output (батч) | $0.20 | $2.50 |
| 1000 объявлений/день | **~$0.04** (~$1.2/мес) | **~$0.85** (~$25/мес) |
| Качество русского | хорошее | отличное |
| Structured output | JSON schema mode | tool use + Pydantic — самый стабильный |
| Когда брать | бюджет, простые критерии | сложный бриф, тонкое ранжирование |

**Рекомендация:** начать на **GPT-4.1 nano batch**, если качество скоринга не устроит — переключить ENV-переменную на **Haiku 4.5**. Структура кода через `instructor` — единая, провайдер меняется одной строкой.

### Промпт + structured output

```python
from pydantic import BaseModel, Field
import instructor
from anthropic import Anthropic

class ListingScore(BaseModel):
    score: int = Field(ge=1, le=10, description="1-10, насколько подходит под бриф")
    reasoning: str = Field(description="Краткое объяснение, 1-3 предложения")
    pros: list[str]
    cons: list[str]
    brand: str
    model: str
    year: int
    mileage_km: int
    price_eur: int

client = instructor.from_anthropic(Anthropic())

USER_BRIEF = """<твой длинный бриф: что ты ищешь, бюджет, требования
к мотору/коробке/полному приводу, что критично, что nice to have ...>"""

# КЭШИРУЕМ системный промпт — экономия 90% на нём при повторных вызовах.
# ВАЖНО: для Haiku 4.5 минимум для cache_control = 4096 токенов.
# Если бриф короче, добавь развёрнутые примеры оценок.
SYSTEM = [{
    "type": "text",
    "text": f"Ты автоэксперт. Оцени объявление по брифу.\n\nБРИФ:\n{USER_BRIEF}",
    "cache_control": {"type": "ephemeral", "ttl": "1h"},
}]

def score_listing(listing_text: str) -> ListingScore:
    return client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=600,
        system=SYSTEM,
        messages=[{"role": "user", "content": listing_text}],
        response_model=ListingScore,
    )
```

### Batch API (сразу после MVP)

При ежедневном прогоне в 1–2 часа ночи — никакой задержки нет, зато **скидка 50%** к input/output. Стэкуется с prompt caching → итоговая экономия до 95% на системной части.

- Anthropic: `client.messages.batches.create(...)`, до 10 000 запросов в батче.
- OpenAI: `client.batches.create(input_file_id=...)`, до 100 000 / 256 MB.

### Сколько токенов закладывать

- Системный промпт (бриф + критерии): ~3000 токенов (для Haiku 4.5 нужно 4096+ для кэша — добей примерами).
- Объявление: ~400–800 input.
- Ответ: ~200 output.

---

## 4. Google Sheets как «таблица»

### Подготовка (10 минут)

1. Создать GCP-проект → Enable **Google Sheets API** + **Google Drive API**.
2. Создать **Service Account**, скачать `creds.json`.
3. Создать таблицу в Google Sheets, **расшарить её на email сервис-аккаунта** (`xxx@yyy.iam.gserviceaccount.com`) с правами Editor.
4. `pip install gspread gspread-formatting`.

### Структура таблицы

Лист **`listings`** (основной):

| listing_id | url | first_seen | last_seen | brand | model | year | mileage_km | price_eur | location | score | reasoning | pros | cons | status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

Лист **`price_history`**:

| listing_id | changed_at | old_price | new_price |
|---|---|---|---|

Лист **`runs`** (служебный, для мониторинга):

| run_at | new_count | updated_count | removed_count | errors |
|---|---|---|---|---|

### Скелет интеграции

```python
import gspread
from gspread.utils import ValueInputOption

gc = gspread.service_account(filename="creds.json")
sh = gc.open_by_key("SPREADSHEET_ID")
ws_listings = sh.worksheet("listings")

# Дедуп: подтянуть существующие ID одним вызовом
existing = {row["listing_id"]: idx + 2  # +2: header + 1-based
            for idx, row in enumerate(ws_listings.get_all_records())}

new_rows, updates = [], []
for item in scored_items:                       # из парсера + LLM
    if item["listing_id"] in existing:
        row_idx = existing[item["listing_id"]]
        # обновляем last_seen, и если price изменился — пишем в price_history
        ...
    else:
        new_rows.append([
            item["listing_id"], item["url"], today, today,
            item["brand"], item["model"], item["year"],
            item["mileage_km"], item["price_eur"], item["location"],
            item["score"], item["reasoning"],
            "; ".join(item["pros"]), "; ".join(item["cons"]),
            "active",
        ])

if new_rows:
    ws_listings.append_rows(new_rows, value_input_option=ValueInputOption.user_entered)
```

### Условное форматирование (один раз)

```python
from gspread_formatting import (
    ConditionalFormatRule, GridRange, BooleanRule,
    BooleanCondition, CellFormat, Color, get_conditional_format_rules,
)

rules = get_conditional_format_rules(ws_listings)
rules.append(ConditionalFormatRule(
    ranges=[GridRange.from_a1_range("K2:K10000", ws_listings)],  # колонка score
    booleanRule=BooleanRule(
        condition=BooleanCondition("NUMBER_GREATER_THAN_EQ", ["8"]),
        format=CellFormat(backgroundColor=Color(0.7, 1.0, 0.7)),  # зелёный
    ),
))
rules.save()
```

### Лимиты Sheets API (бесплатно)

- 60 запросов/мин на пользователя на проект (лимит читается; запись чуть жирнее).
- 10 млн ячеек на таблицу — на годы вперёд.
- **Главное**: батчить операции (`append_rows`, `batch_update`), а не построчно — иначе упрёшься в rate limit за минуты.

---

## 5. Дедупликация и трекинг изменений

- **listing_id** из `__NEXT_DATA__` — PRIMARY KEY. `INSERT OR IGNORE` логика на стороне Python.
- **last_seen** — обновляется при каждом обнаружении; если `< NOW() - 2 дня` → ставим `status = 'removed'`.
- **price_history** — сравниваем new vs old price; если != → пишем строку в лист `price_history` и обновляем `price_eur` в `listings`.
- **first_seen** — для подсветки «новых за последние 24 часа».

---

## 6. Ежедневный запуск

### Хостинг — Hetzner CAX11 (€3.49/мес, ARM, 4GB RAM, EU IP)

EU-IP важен: с российских IP `api.anthropic.com` и `api.openai.com` периодически возвращают 403. Hetzner — без проблем.

Альтернатива при оплате с РФ-карты невозможной: купить через посредника (vpsville/donaiserv) или использовать **Gemini 2.5 Flash-Lite** (Google РФ напрямую не блочит) с Timeweb VPS.

### systemd timer

`/etc/systemd/system/autoscout-pipeline.service`:
```ini
[Unit]
Description=Autoscout pipeline
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/autoscout
EnvironmentFile=/opt/autoscout/.env
ExecStart=/opt/autoscout/.venv/bin/python -m pipeline
```

`/etc/systemd/system/autoscout-pipeline.timer`:
```ini
[Unit]
Description=Daily autoscout run

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl enable --now autoscout-pipeline.timer
journalctl -u autoscout-pipeline.service -f   # логи
```

### Альтернатива без VPS

GitHub Actions schedule на **публичном** репо (бесплатно, без лимита минут). Минусы: 10–30 мин дрифта расписания, отключение workflow после 60 дней без коммитов.

---

## 7. Уведомления (опционально, +30 мин)

Telegram Bot API: при `score >= 8` отправляешь себе сообщение со ссылкой и summary.

```python
import httpx
def notify(text: str):
    httpx.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": False},
        timeout=10,
    )
```

---

## 8. Архитектура — финальная схема

```
┌──────────────────┐    daily 03:00
│  systemd timer   │────────────┐
└──────────────────┘            ▼
                  ┌───────────────────────────┐
                  │  pipeline.py              │
                  │                           │
                  │  1. fetch /lst pages      │  ◄── curl_cffi + Akamai cookies
                  │  2. extract __NEXT_DATA__ │
                  │  3. dedup vs Sheets       │
                  │  4. LLM batch scoring     │  ◄── instructor + Haiku/nano
                  │  5. write to Sheets       │  ◄── gspread batch_update
                  │  6. notify if score>=8    │  ◄── Telegram Bot
                  └───────────────────────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │  Google Sheets   │
                  │  ├ listings      │
                  │  ├ price_history │
                  │  └ runs          │
                  └──────────────────┘
```

---

## 9. Порядок реализации

1. **День 1, 1–2 часа.** Поставить `curl_cffi`, написать `fetch_page` + извлечение `__NEXT_DATA__`. Проверить, что без проксей отдаётся реальный JSON. Залить 1 страницу руками в Sheets.
2. **День 1, 1 час.** Подключить `gspread` + service account. Написать дедуп по `listing_id`, append новых.
3. **День 2, 2 часа.** Подключить `instructor` + Pydantic-модель. Сначала на GPT-4.1 nano (дешевле всего экспериментировать). Прогнать 20 объявлений, посмотреть на качество score.
4. **День 2, 30 мин.** Условное форматирование колонки score, фильтр по `>= 7`.
5. **День 3, 1 час.** Деплой на Hetzner: systemd timer + cron. Логи в journald.
6. **День 3, 30 мин.** Telegram-уведомления.
7. **Неделя 2.** Если объём вырос — переехать на batch API (Anthropic / OpenAI) + prompt caching.
8. **Если ловишь 403 от Akamai** — добавь residential EU-прокси, потом camoufox.

---

## 10. Риски и подводные камни

| Риск | Митигация |
|---|---|
| Akamai жёстко блочит после N запросов | Residential EU-прокси, ротация между сессиями, паузы 5–10 сек, fallback на camoufox |
| Anthropic/OpenAI 403 с РФ IP | Хостить в EU (Hetzner). Или Gemini Flash-Lite |
| Структура `__NEXT_DATA__` поменяется | Парсить с защитой (`.get()`), логировать unexpected schema, alert в Telegram |
| Sheets API rate limit | Только batch-операции (`append_rows`, `batch_update`), не построчно |
| Haiku 4.5 не кэширует промпт <4096 токенов | Добить системный промпт примерами, либо взять Haiku 3.5 (порог 2048) |
| Cache TTL 5 минут (новый дефолт Anthropic) | Указать явно `"ttl": "1h"` в `cache_control` для дневных батчей |
| Платёжка для Hetzner с РФ-карт | Wise / иностранная карта / посредник; либо Timeweb + Gemini |

---

## Источники

**Парсинг autoscout24:**
- Scrapfly — [How to Scrape AutoScout24 in 2026](https://scrapfly.io/blog/posts/how-to-scrape-autoscout24)
- Scrape.do — [Scraping AutoScout24 без блокировок](https://scrape.do/blog/autoscout24-scraping/)
- [autoscout24.com/robots.txt](https://www.autoscout24.com/robots.txt)
- [lexiforest/curl_cffi](https://github.com/lexiforest/curl_cffi)
- [daijro/camoufox](https://github.com/daijro/camoufox)
- Scrapfly — [Bypassing Akamai 2026](https://scrapfly.io/blog/posts/how-to-bypass-akamai-anti-scraping)
- Apify — [autoscout24-scraper actors](https://apify.com/blackfalcondata/autoscout24-scraper)

**LLM:**
- [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- [Anthropic Prompt Caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Anthropic Batch API](https://platform.claude.com/docs/en/build-with-claude/batch-processing)
- [OpenAI API Pricing](https://openai.com/api/pricing/)
- [GPT-4.1 nano breakdown](https://pricepertoken.com/pricing-page/model/openai-gpt-4.1-nano)
- [Claude Haiku 4.5 pricing](https://pricepertoken.com/pricing-page/model/anthropic-claude-haiku-4.5)
- [instructor — Pydantic structured output](https://python.useinstructor.com/)

**Google Sheets:**
- [gspread docs](https://docs.gspread.org/)
- [gspread-formatting](https://pypi.org/project/gspread-formatting/)
- [Sheets API quotas](https://developers.google.com/sheets/api/limits)

**Хостинг / оркестрация:**
- [Hetzner Cloud](https://www.hetzner.com/cloud)
- [Timeweb Cloud VPS](https://timeweb.cloud/services/vds-vps)
- [GitHub Actions schedule limits](https://docs.github.com/en/actions/reference/limits)
