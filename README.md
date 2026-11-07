# Голосовое управление Home Assistant через Яндекс Станцию

Алиса на колонке понимает команды умного дома, выполняет их в Home Assistant и отвечает голосом Алисы. Логика и правила — **одни и те же**, что у ассистента в HA (Assist): промпт живёт в Home Assistant, а не на колонке.

Работает в связке:

- **[extended_openai_conversation](https://github.com/jekalmin/extended_openai_conversation)** (EOC) — conversation-агент в HA: промпт, функции, вызов сервисов;
- **Quasar Bridge** на колонке — перехватывает голос Алисы и решает, кто ответит: Яндекс, модель или HA;
- **HA Agent Proxy** — маленький аддон в HA, который притворяется OpenAI-совместимой моделью и пересылает запросы в HA-агент;
- **Home Assistant** — сущности, устройства, сервисы;
- **DeepSeek** — модель, которая думает внутри EOC.

---

## 1. Схема

```
«Алиса, включи пение птиц на бризере в кабинете»
        │
        ▼
Яндекс Станция (root + SSH)
  Quasar Bridge  ──►  правила маршрутизации
        │                   │
        │                   ├─ музыка, погода, таймеры, будильники → Яндекс (как обычно)
        │                   └─ всё остальное → HA Agent Proxy
        ▼
HA Agent Proxy (аддон, порт 8777)
   POST /v1/chat/completions  (формат OpenAI, в т.ч. stream)
        │  вытаскивает реплику пользователя, добавляет уточняющий вопрос из истории
        ▼
HA: POST /api/conversation/process
   agent_id: conversation.extended_openai_conversation
        │
        ▼
EOC «DeepSeek» — промпт + функции
   find_entities, set_select_option, turn_on/off, execute_services, Emby…
        │
        ▼
Home Assistant: select.select_option / switch.turn_on / climate.set_temperature …
        │
        ▼
Ответ (текст или пусто) → прокси → мост → Алиса озвучивает
```

---

## 2. Что нужно

1. **Яндекс Станция с root и SSH.**
   Инструкции по получению root и SSH для разных моделей: <https://hackalice.me/> (раздел «Начало работы» → «Получение root»).
2. **Quasar Bridge** на колонке — рецепт «Своя LLM вместо Алисы»: <https://hackalice.me/recipes/llm/>.
   Установщик спросит адрес модели и (опционально) MCP-сервер Home Assistant.
3. **Home Assistant** с установленным **extended_openai_conversation** (через HACS или вручную, см. репозиторий).
4. **Ключ DeepSeek** (или любого OpenAI-совместимого провайдера) для EOC.
5. **Аддон HA Agent Proxy** в HA (файлы ниже) — он и делает «мост» между колонкой и HA-агентом.

---

## 3. Как это работает

- Колонка больше **не решает сама**, что она умеет. Quasar Bridge только маршрутизирует запрос: Яндекс или наш агент.
- Наш агент — обычный conversation-агент HA, у него есть промпт и функции. Поэтому любые устройства и режимы (select, climate, свет, розетки, скрипты) обрабатываются **одним и тем же кодом**: сначала поиск сущности (`find_entities`), потом действие (`set_select_option`, `turn_on_entity`, `turn_off_entity`, `execute_services`).
- Новое устройство не требует ни скриптов, ни правок на колонке: достаточно, чтобы оно было в HA.
- Прокси нужен потому, что мост умеет говорить только с OpenAI-совместимым API, а HA-агент такого API наружу не отдаёт.
- Ответ пустой (обычная команда) → прокси отдаёт точку, и Алиса молчит. Мост не принимает пустой ответ и считает его ошибкой.
- Ответ с уточняющим вопросом → мост слушает дальше, а прокси передаёт вопрос агенту вместе со следующей репликой («Ответ на уточняющий вопрос «…»: в кабинете»), чтобы агент понял контекст.

---

## 4. Один промпт на всё

Промпт хранится **в Home Assistant**, в настройках субагента EOC (Settings → Devices & Services → Extended OpenAI Conversation → DeepSeek → Configure). Он же используется:

- в Assist (текстовый/голосовой ассистент в HA);
- на колонке — через прокси.

Поэтому правила правятся в одном месте и сразу действуют везде. В промпте:

- правила ответа и **тишины** (на команды — пустой ответ);
- правило «уточняй или выполняй, но не одновременно» и «комната не названа, а устройств несколько → вопрос»;
- правила света (основной/декоративный);
- словарь звуков бризера (пение птиц = birdsong и т.д.);
- Emby;
- автоматически собираемые таблицы:
  - **раздел 9** — устройства, экспортированные в Assist (с вариантами `select`, режимами `climate`, скоростями `fan`);
  - **раздел 10** — варианты и режимы **всех** `select`/`input_select`/`climate`, даже не экспортированных (Jinja по `states`).

Функции агента (в том же конфиге EOC):

| Функция | Зачем |
| --- | --- |
| `find_entities(query)` | найти сущности по слову (комната, прибор), вернуть `entity_id | имя | состояние | варианты` |
| `set_select_option(entity_id, option)` | поставить любой вариант любому `select` (звуки, режимы) |
| `set_input_select_option` | то же для `input_select` |
| `turn_on_entity` / `turn_off_entity` | включить/выключить любую сущность по id |
| `execute_services` | свет, розетки, шторы, вентиляторы, увлажнители, пылесос, медиа |
| `set_climate_temperature` | температура |
| `media_control` | play/pause/stop/rewind/fast_forward |
| `play_emby_content_by_name(query, device)` | фильм/сериал из Emby (ТВ или ноутбук) |
| `list_unfinished_series` | недосмотренные сериалы |

Функции `set_select_option`/`turn_on_entity` сделаны скриптовыми, поэтому работают **даже для неэкспортированных в Assist сущностей** — в отличие от встроенного `execute_services`, который требует экспозиции.

---

## 5. Настройка по шагам

### 5.1. Home Assistant

1. Установить **extended_openai_conversation**.
2. Создать субагента: модель `deepseek-chat`, ключ DeepSeek.
3. Вставить промпт и функции (см. раздел 4).
4. Проверить в Assist: «включи свет в кабинете», «какие звуки есть у бризера в кабинете?».

### 5.2. Аддон HA Agent Proxy

Папка `/addons/ha_agent_proxy/`:

**config.yaml**

```yaml
name: HA Agent Proxy
version: "1.0.1"
slug: ha_agent_proxy
description: OpenAI-compatible proxy to the Home Assistant conversation agent
arch:
  - aarch64
  - amd64
startup: application
boot: auto
init: false
hassio_api: true
homeassistant_api: true
ports:
  "8777/tcp": 8777
```

**Dockerfile**

```dockerfile
FROM python:3.12-alpine
COPY proxy.py /proxy.py
CMD ["python3", "/proxy.py"]
```

**proxy.py** — см. актуальную версию из чата (OpenAI-формат, SSE, повторы при «грязных» ответах, передача уточняющего вопроса, `.` вместо пустого ответа).

Установка: Settings → Add-ons → Add-on Store → ⋮ → Check for updates → Local add-ons → **HA Agent Proxy** → Install → Start.
Проверка: `http://<ip-ха>:8777/` → `{"ok": true, "token_len": ...}`.

### 5.3. Колонка (Quasar Bridge)

`/data/opt/quasar-bridge/runtime.env`:

```sh
QUASAR_MODE="hybrid"
QUASAR_LLM_BASE_URL="http://<ip-ха>:8777/v1"
QUASAR_LLM_MODEL="ha-agent"
QUASAR_LLM_API="chat_completions"
QUASAR_LLM_API_KEY="proxy"
```

`/data/opt/quasar-bridge/config.json`:

```json
{
  "listen": "127.0.0.1:8443",
  "mode": "hybrid",
  "allowed_ips": ["127.0.0.1", "::1"],
  "listen_after_reply": true,
  "local_progress": {"enabled": true},
  "routing": {
    "default_route": "llm",
    "rules": [
      {"name": "speaker_playback", "route": "yandex", "match": {"regex": "..."}},
      {"name": "yandex_services", "route": "yandex", "match": {"contains_any": ["погода", "таймер", "музыку", "радио", "песню", "трек", "который час", "день недели"]}},
      {"name": "device_control_llm", "route": "llm", "match": {"contains_any": ["включи", "выключи", "открой", "закрой", "поставь", "установи", "переключи", "прибавь", "убавь", "запусти", "горит", "включен", "выключен"], "contains_none": ["музык", "песн", "трек", "радио", "подкаст", "погод", "таймер", "будильник"]}}
    ]
  }
}
```

- **Правила `yandex`** оставляют Яндексу музыку, погоду, таймеры, будильники.
- **`default_route: llm`** — всё остальное уходит нашему агенту (без классификатора: он тоже ходил в LLM и ломался).
- **`listen_after_reply: true`** — после уточняющего вопроса колонка ждёт ответ.
- **`home`-маршрут не используется**: он умеет только фиксированный набор доменов (свет, розетки, климат, шторы, вентилятор, пылесос, медиа) и не умеет `select` — именно поэтому «пение птиц» там было невозможно.

Перезапуск: `sh app/control.sh restart`, проверка: `sh app/control.sh status`.

### 5.4. Проверка

```sh
cd /data/opt/quasar-bridge
set -a; . ./runtime.env; set +a
./app/bin/quasar-bridge -config config.json -query "выключи кондей"
```

Ожидаемо: `Route: llm` для команд, `yandex` для музыки/погоды.

Голосом:
1. «включи пение птиц на бризере в кабинете» — включит и промолчит;
2. «выключи кондей» при одном работающем — выключит его; при двух — спросит и дождётся;
3. «включи музыку» — Яндекс.

---

## 6. Зачем каждый конфиг

### `runtime.env` (колонка)

Переменные окружения Quasar Bridge: адрес модели (у нас — прокси), её имя, ключ, режим API и секретный URL HA-MCP. Мост читает их при старте (`start.sh` подхватывает файл).

### `config.json` (колонка)

Поведение моста: на каком порту слушать, кого слушать, **правила маршрутизации** (что Яндексу, что агенту), ждать ли продолжения после ответа.

### Аддон HA Agent Proxy

Принимает запросы в формате OpenAI (`/v1/chat/completions`), вытаскивает реплику, вызывает HA-агент, возвращает ответ. Умеет:

- SSE-стрим (мост ждёт потоковый ответ);
- повтор при «грязных» ответах модели (DSML-разметка) — до 5 попыток;
- подстановку уточняющего вопроса в следующую реплику;
- замену пустого ответа на `.` (мост не принимает пустоту, а точку не озвучивает).

### extended_openai_conversation (HA)

Сам агент: промпт + функции + ключ модели. Здесь же — таблицы устройств, собираемые Jinja-шаблонами на каждом запросе.

---

## 7. Известные ограничения

- **DeepSeek иногда «ломает» вызов функции** и пишет её текстом (`<｜｜DSML｜｜ …>`). Прокси отбрасывает такие ответы и повторяет запрос; при 5 неудачах говорит «Не получилось выполнить команду, повторите».
- **Пустой ответ** мост считает ошибкой, поэтому прокси отдаёт `.` — Алиса молчит.
- **Задержка** на команды — 2–4 секунды (запрос к модели).
- **Зависимость от аддона**: если HA или аддон лежит, колонка на команды скажет «не получилось получить ответ».
- **Уточняющие вопросы** работают только при `listen_after_reply: true` и передаче контекста в прокси.

---

## 8. Бэкапы и откат

На колонке:

```sh
cd /data/opt/quasar-bridge
cp config.json config.json.bak
cp runtime.env runtime.env.bak
sh app/control.sh restart
```

Откат: вернуть `runtime.env.bak` и `config.json.bak`, перезапустить мост. Полный откат на Алису — по инструкции hackalice («Как вернуть Алису»).

---

## 9. Ссылки

- Quasar Bridge — <https://github.com/skrashevich/quasar-bridge>
- hackalice (root, SSH, рецепты, «Своя LLM вместо Алисы») — <https://hackalice.me/>
- extended_openai_conversation — <https://github.com/jekalmin/extended_openai_conversation>
- DeepSeek API — <https://api.deepseek.com>

---

## 10. Приложение: настройки и промпт EOC

### Параметры субагента «DeepSeek»

Settings → Devices & Services → Extended OpenAI Conversation → **DeepSeek** → Configure:

| Параметр | Значение |
| --- | --- |
| `chat_model` | `deepseek-chat` |
| `temperature` | `0.2` |
| `top_p` | `1.0` |
| `max_tokens` | `2048` |
| `max_function_calls_per_conversation` | `4` |
| `use_tools` | `true` |
| `context_threshold` | `13000` |
| `context_truncate_strategy` | `clear` |
| `attach_username` | `false` |

### Промпт (поле `prompt`, вставлять целиком)
<details>
<summary>Развернуть: полный промпт</summary>
  
````yaml
You are the voice assistant of the Home Assistant installation "{{ ha_name }}". You control a real apartment and speak to its owner in Russian.

=== 0. ОБЩИЕ ПРАВИЛА (одинаковы для Assist и для MCP-клиента) ===
1. Язык и формат.
1.1. Отвечай по-русски, обычным текстом, одной короткой фразой. Без markdown, списков, эмодзи и кавычек вокруг ответа.
1.2. В ответе — только обычный текст для озвучки. Никаких тегов, разметки, имён функций, параметров и служебных токенов.
1.3. Никогда не пиши вызов инструмента текстом — только реальный вызов.

2. Тишина.
2.1. На любую команду (в том числе после вызова функций) ответ должен быть ПУСТЫМ. На обычную команду (свет, розетка, реле, климат, бризер, шторы, вентилятор, увлажнитель, пылесос, громкость, воспроизведение, сценарий) — выполни и верни ПУСТОЙ ответ. Запрещены «Готово», «Включил», «Выключил», «Сделано», «Ок», «Принято». После вызова функций действия (execute_services, set_select_option, set_input_select_option, turn_on_entity, turn_off_entity, set_climate_temperature, media_control) ответ всегда пустой — никаких подтверждений и никаких уточняющих вопросов после выполненного действия. Сначала либо уточни, либо выполни; одновременно нельзя. Если комната не названа, а подходящих устройств несколько — задай ОДИН короткий вопрос и НИЧЕГО не выполняй до ответа. Если действие уже выполнено — вопрос не задавай. Никогда не применяй действие ко всем устройствам без явной просьбы «все», «везде», «во всех комнатах».
2.2. Говори только если: (а) задан вопрос; (б) это Emby (раздел 5); (в) это ошибка, которую надо озвучить.
2.3. Пустой ответ — это норма, а не ошибка. Никогда не заменяй его на «Готово», «Ок» или любое другое подтверждение.

2.4. Команда без комнаты, а устройств несколько: сначала посмотри состояния. Если под условие подходит РОВНО ОДНО устройство (только оно включено / только оно выключено / только у него включён режим) — действуй на нём сразу, без вопроса. Если подходят два и более (оба включены, оба играют, оба выключены) — задай ОДИН короткий вопрос и НИЧЕГО не выполняй до ответа. Никогда не применяй действие ко всем устройствам без явной просьбы «все», «везде», «во всех комнатах».

3. Сущности.
3.1. Используй только реальные entity_id: из таблицы устройств (Assist) или из результатов поиска (MCP). Никогда не выдумывай entity_id, сервисы и имена функций.
3.2. Не знаешь entity_id — сначала найди по имени или комнате, потом действуй.
3.3. Если подходящих устройств несколько, а комната не названа — задай один короткий вопрос с вариантами.
3.4. Несколько действий в одной фразе — вызывай по одному устройству за вызов.
3.5. Не повторяй уже успешный вызов.

4. Функции, которых нет отдельной сущностью.
4.1. «Пение птиц», «дождь», «море», «лес», «костёр», «ночной режим», «турбо», «эко» и подобное — это значения options у select или preset_modes/fan_modes у climate.
4.2. Прежде чем сказать, что функции нет, проверь раздел 10 (варианты и режимы ВСЕХ устройств) и таблицу устройств.
4.3. Если формулировка совпала с вариантом — вызови set_select_option(entity_id, option) с ТОЧНЫМ значением из списка «варианты». Для input_select — set_input_select_option. Для климата — set_climate_temperature/set_preset_mode. При необходимости включи связанный switch (например, «Звук») через execute_services.
4.4. Если не совпало — скажи: «У <устройство> нет режима «X». Доступно: <перечисли варианты>».
4.5. Если устройство или функция не попали в таблицу — вызови find_entities(query) и ищи по названию прибора или комнаты. Нашёл — действуй (set_select_option, turn_on_entity, turn_off_entity).

4.6. Свет. «Включи свет в <комнате>» = основной свет комнаты: сущность, в названии которой есть «основной» (обычно это switch-реле). Лампа, подсветка, фоновая подсветка, торшер, бра — декоративные: включай их только если пользователь назвал их отдельно или сказал «весь свет», «всё», «все лампы». Если основной свет недоступен — скажи об этом.

4.7. Значения звуков бризера: «пение птиц/птицы» = birdsong (Птицы), «дождь» = rainstorm (Дождь), «море» = surf (Море), «лес» = forest (Лес), «костёр» = bonfire (Костер), «выключить звуки» = mute (Выключено). У бризера в кабинете и в детской могут быть две сущности с вариантами (английские и русские) — это одно и то же устройство, достаточно одной.

5. Emby.
5.1. «Включи/поставь фильм или сериал X» — вызови функцию воспроизведения Emby ровно один раз, передав только название (без «включи», «поставь», «запусти») и устройство.
5.2. Устройство: «ноутбук», «ноут», «компьютер», «Асус», «на ноуте» -> laptop; «телевизор», «телек», «ТВ» или устройство не названо -> tv.
5.3. Ответ пользователю — ровно тот текст, который вернула функция. Не выдумывай успех и не говори «Включаю» до результата.
5.4. Если функция вернула «Не нашёл …» или «Нет непросмотренных серий» — произнеси это дословно.
5.5. Продолжение с места остановки решает функция, отдельно про это не спрашивай.

6. Безопасность.
6.1. Делай только то, о чём попросили. Не добавляй устройства, режимы и сцены от себя.
6.2. Не удаляй сущности, не перезагружай Home Assistant и не меняй настройки интеграций без явной просьбы.

7. Ошибки.
7.1. Инструмент вернул ошибку — коротко скажи, что не получилось и что нужно (например: «Бризер не на связи»).

=== ФУНКЦИИ ASSIST ===
Доступны только: play_emby_content_by_name, list_unfinished_series, execute_services, set_climate_temperature, media_control.
8.1. play_emby_content_by_name(query, device): query — только название; device — tv или laptop по правилу 5.2.
8.2. Функция возвращает JSON {"result": "<фраза>"}. Это единственная правда о результате. Твой ответ — ровно эта фраза, символ в символ.
8.3. Если result пустой, равен "{}" или вызов упал — скажи: Не удалось получить ответ от Emby.
8.4. «Какие сериалы я не досмотрел» — вызови list_unfinished_series и ответь её результатом дословно.
8.5. execute_services — по одному устройству за вызов: свет, розетки, реле, климат, шторы, вентиляторы, увлажнители, пылесос, медиа.
8.6. set_climate_temperature — только для запросов температуры.
8.7. media_control — play_pause, stop, rewind, fast_forward на телевизоре.
8.8. Функций get_state, get_entities, get_entity_state, get_attributes и get_history НЕТ. Состояния уже в таблице.

=== 9. ТАБЛИЦА УСТРОЙСТВ (current states) ===
```csv
entity_id|name|state
{% set domains = ['light','switch','climate','cover','fan','humidifier','vacuum','media_player','script','scene','input_boolean','remote','water_heater','lock','valve','number','select','button'] %}
{% set extra = ['sensor.time','sensor.date','sensor.temperatura_v_kvartire','sensor.vlazhnost_v_kvartire','sensor.yandex_weather_temperature_3','sensor.yandex_weather_feels_like_temperature_3','sensor.home1364_temperature','sensor.home1364_humidity','weather.forecast_home1364','weather.home1364'] %}
{% for e in exposed_entities -%}
{% if (e.entity_id.split('.')[0] in domains or e.entity_id in extra) and e.state not in ['unavailable','unknown'] -%}
{{ e.entity_id }}|{{ e.name }}|{{ e.state }}{% set opts = state_attr(e.entity_id, 'options') %}{% set pm = state_attr(e.entity_id, 'preset_modes') %}{% set fm = state_attr(e.entity_id, 'fan_modes') %}{% if opts is not none %} (варианты: {{ opts | join(' / ') }}){% endif %}{% if pm is not none %} (режимы: {{ pm | join(' / ') }}){% endif %}{% if fm is not none %} (скорости: {{ fm | join(' / ') }}){% endif %}
{% endif -%}
{% endfor -%}
```

=== 10. ВСЕ ВАРИАНТЫ И РЕЖИМЫ (автоматически, включая неэкспортированные) ===
```csv
entity_id|name|state|варианты
{% set exposed_ids = exposed_entities | map(attribute='entity_id') | list %}
{% for s in states.select %}{% if s.entity_id not in exposed_ids and s.state not in ['unavailable','unknown'] and state_attr(s.entity_id,'options') %}{{ s.entity_id }}|{{ s.name }}|{{ s.state }}|{{ state_attr(s.entity_id,'options') | join(' / ') }}
{% endif %}{% endfor %}
{% for s in states.input_select %}{% if s.entity_id not in exposed_ids and s.state not in ['unavailable','unknown'] %}{{ s.entity_id }}|{{ s.name }}|{{ s.state }}|{{ state_attr(s.entity_id,'options') | join(' / ') }}
{% endif %}{% endfor %}
{% for s in states.climate %}{% if s.entity_id not in exposed_ids %}{{ s.entity_id }}|{{ s.name }}|{{ s.state }}|режимы: {{ state_attr(s.entity_id,'preset_modes') | join(' / ') }}; скорости: {{ state_attr(s.entity_id,'fan_modes') | join(' / ') }}
{% endif %}{% endfor %}
```

4.8. Примеры команд (не трогай устройства, которых нет в команде):
— «выключи пение птиц»: найди бризер, у которого мелодия сейчас birdsong, и вызови set_select_option(mute) только у него. Кондиционер, климат и прочее не трогай.
— «включи дождь на бризере в кабинете»: set_select_option(rainstorm) у бризера в кабинете.
— «выключи кондей»: если работает один — выключи его; если оба — спроси, какой.
````
</details>

### Функции (поле `functions`, YAML)
<details>
<summary>Развернуть: параметры субагента, полный промпт и функции</summary>

```yaml
- spec:
    name: play_emby_content_by_name
    description: >-
      Play a movie, TV series or cartoon from the Emby library on the living-room TV.
      Call this function exactly once when the user asks to watch something from Emby.
      The function returns the exact phrase that must be said to the user.
    parameters:
      type: object
      properties:
        query:
          type: string
          description: >-
            Title of the movie or series exactly as the user said it,
            without command words like "включи", "поставь", "запусти".
        device:
          type: string
          enum:
            - tv
            - laptop
          description: >-
            Playback target. Use "laptop" when the user says ноутбук, ноут, компьютер, Асус, на ноуте.
            Use "tv" for телевизор, телек, ТВ or when the device is not mentioned.
      required:
        - query
  function:
    type: script
    sequence:
      - action: script.emby_play_movie
        data:
          movie_title: "{{ query | default('') }}"
          device: "{{ device | default('tv', true) }}"
        response_variable: _function_result
        continue_on_error: true
      - variables:
          _function_result: >-
            {{ _function_result['message'] if (_function_result is defined
               and _function_result is mapping
               and 'message' in _function_result) else 'Не удалось получить ответ от Emby.' }}

- spec:
    name: execute_services
    description: Execute Home Assistant services for lights, switches, covers, scripts and media players.
    parameters:
      type: object
      properties:
        list:
          type: array
          items:
            type: object
            properties:
              domain:
                type: string
              service:
                type: string
              service_data:
                type: object
                properties:
                  entity_id:
                    type: string
                required:
                  - entity_id
            required:
              - domain
              - service
              - service_data
      required:
        - list
  function:
    type: native
    name: execute_service

- spec:
    name: set_climate_temperature
    description: Set the target temperature of a climate entity. Use only for temperature requests.
    parameters:
      type: object
      properties:
        entity_id:
          type: string
        temperature:
          type: number
      required:
        - entity_id
        - temperature
  function:
    type: script
    sequence:
      - action: climate.set_temperature
        target:
          entity_id: "{{ entity_id }}"
        data:
          temperature: "{{ temperature }}"

- spec:
    name: media_control
    description: Control playback on the living-room Android TV.
    parameters:
      type: object
      properties:
        command:
          type: string
          enum:
            - play_pause
            - stop
            - rewind
            - fast_forward
      required:
        - command
  function:
    type: script
    sequence:
      - choose:
          - conditions:
              - condition: template
                value_template: "{{ command == 'play_pause' }}"
            sequence:
              - action: media_player.media_play_pause
                target:
                  entity_id: media_player.android_tv_192_168_1_102
          - conditions:
              - condition: template
                value_template: "{{ command == 'stop' }}"
            sequence:
              - action: media_player.media_stop
                target:
                  entity_id: media_player.android_tv_192_168_1_102
          - conditions:
              - condition: template
                value_template: "{{ command == 'rewind' }}"
            sequence:
              - action: androidtv.adb_command
                target:
                  entity_id: media_player.android_tv_192_168_1_102
                data:
                  command: input keyevent KEYCODE_MEDIA_REWIND
          - conditions:
              - condition: template
                value_template: "{{ command == 'fast_forward' }}"
            sequence:
              - action: androidtv.adb_command
                target:
                  entity_id: media_player.android_tv_192_168_1_102
                data:
                  command: input keyevent KEYCODE_MEDIA_FAST_FORWARD

- spec:
    name: list_unfinished_series
    description: >-
      Report how many TV series in Emby still have unwatched episodes and which ones have the most left.
      Use when the user asks what series they have not finished watching.
    parameters:
      type: object
      properties:
        dummy:
          type: string
          description: Nothing, pass an empty string.
      required:
        - dummy
  function:
    type: script
    sequence:
      - action: script.emby_unwatched_series
        response_variable: _function_result
        continue_on_error: true
      - variables:
          _function_result: >-
            {{ _function_result['message'] | trim if (_function_result is defined
               and _function_result is mapping
               and 'message' in _function_result) else 'Не удалось получить список из Emby.' }}

- spec:
    name: set_select_option
    description: >-
      Set a value on any select entity (device mode, sound, feature). Use it when the user asks for
      something that exists as an option in the "варианты" list of the device, e.g. birdsong, rainstorm,
      surf, forest, bonfire. Pass the exact entity_id and the exact option string from that list.
    parameters:
      type: object
      properties:
        entity_id:
          type: string
          description: Exact entity id of a select entity.
        option:
          type: string
          description: Exact option value from the device's "варианты" list.
      required: [entity_id, option]
  function:
    type: script
    sequence:
      - action: select.select_option
        data:
          entity_id: "{{ entity_id }}"
          option: "{{ option }}"
- spec:
    name: set_input_select_option
    description: >-
      Set a value on any input_select entity, same rules as set_select_option.
    parameters:
      type: object
      properties:
        entity_id:
          type: string
        option:
          type: string
      required: [entity_id, option]
  function:
    type: script
    sequence:
      - action: input_select.select_option
        data:
          entity_id: "{{ entity_id }}"
          option: "{{ option }}"

- spec:
    name: find_entities
    description: >-
      Find Home Assistant entities by a word from the device or room name. Returns lines
      entity_id|name|state|options. Use it when the device or feature is not in the device table,
      or before saying that something is not supported. Example queries: бризер, кабинет, шторы.
    parameters:
      type: object
      properties:
        query:
          type: string
          description: One word or short phrase from the device or room name.
      required: [query]
  function:
    type: script
    sequence:
      - variables:
          _function_result: >-
            {% set q = query | lower | trim %}
            {% set ns = namespace(items=[]) %}
            {% for s in states %}
              {% set nm = s.name if s.name is defined else '' %}
              {% if q and (q in s.entity_id | lower or q in nm | lower) %}
                {% set opts = state_attr(s.entity_id, 'options') %}
                {% set pm = state_attr(s.entity_id, 'preset_modes') %}
                {% set fm = state_attr(s.entity_id, 'fan_modes') %}
                {% set line = s.entity_id ~ '|' ~ nm ~ '|' ~ s.state %}
                {% if opts %}{% set line = line ~ ' (варианты: ' ~ opts | join('/') ~ ')' %}{% endif %}
                {% if pm %}{% set line = line ~ ' (режимы: ' ~ pm | join('/') ~ ')' %}{% endif %}
                {% if fm %}{% set line = line ~ ' (скорости: ' ~ fm | join('/') ~ ')' %}{% endif %}
                {% set ns.items = ns.items + [line] %}
              {% endif %}
            {% endfor %}
            {{ ns.items[:40] | join('\n') if ns.items else 'Ничего не найдено по запросу ' ~ query }}
- spec:
    name: turn_on_entity
    description: >-
      Turn on any entity (light, switch, fan, humidifier, media player, input_boolean) by its exact entity_id.
      Works even if the entity is not in the device table.
    parameters:
      type: object
      properties:
        entity_id:
          type: string
      required: [entity_id]
  function:
    type: script
    sequence:
      - action: homeassistant.turn_on
        data:
          entity_id: "{{ entity_id }}"
- spec:
    name: turn_off_entity
    description: >-
      Turn off any entity by its exact entity_id. Works even if the entity is not in the device table.
    parameters:
      type: object
      properties:
        entity_id:
          type: string
      required: [entity_id]
  function:
    type: script
    sequence:
      - action: homeassistant.turn_off
        data:
          entity_id: "{{ entity_id }}"
```

</details>

---

## 11. Emby: что добавить в HA

Ассистент умеет включать фильмы и сериалы из Emby на телевизоре или ноутбуке и продолжать с места остановки. Для этого в HA должно быть несколько вещей — они не входят в EOC и настраиваются отдельно.

### Что нужно

| Что | Зачем |
| --- | --- |
| Сервер **Emby** + API key | источник фильмов, серий и прогресса просмотра |
| Интеграция **Emby** (`embymedia`) | создаёт сессии-плееры (`media_player.emby_…`) для ТВ, ноутбука и браузера |
| Интеграция **Android TV** (`androidtv`) с ADB | управление телевизором: включение, отправка deep link |
| Приложение **Emby** на телевизоре | принимает ссылку `emby://play/<ServerId>/<ItemId>` |
| Клиент **Emby** на ноутбуке (браузер или приложение) | его сессия используется для `media_player.play_media` |
| Хелпер `input_text.emby_status` (Text) | сюда скрипт пишет последний статус («Телевизор не включается…») |
| Три `rest_command` в `configuration.yaml` | поиск по библиотеке и чтение прогресса через Emby API |
| Три скрипта | `emby_play_movie`, `emby_list_movies`, `emby_unwatched_series` |

### Как это работает

- **Телевизор.** Скрипт включает ТВ (если выключен), затем через ADB отправляет:
  ```
  am start -a android.intent.action.VIEW -d 'emby://play/<ServerId>/<ItemId>'
  ```
  Ждёт, пока сессия `media_player.emby_<тв>_emby_<тв>` станет `playing`/`paused`, и делает `media_seek` на сохранённую позицию.
- **Ноутбук.** Ищет сессию по имени «Ноут Asus» (fallback — `media_player.emby_chrome_windows_emby_chrome_windows`), вызывает `media_player.play_media` с `media_content_type: movie|tvshow`, через 1 секунду делает `media_seek` и ещё раз проверяет позицию.
- **Прогресс** берётся из `UserData.PlaybackPositionTicks` (делится на 10 000 000 — получаются секунды). Поэтому «продолжить с места остановки» работает без отдельных настроек.
- Для сериала сначала запрашиваются непросмотренные серии и берётся первая; если серий нет — возвращается «Нет непросмотренных серий».

### rest_command (пример, подставь свой сервер и ключ)

```yaml
rest_command:
  search_emby_movie:
    url: >-
      http://192.168.1.50:8096/emby/Items?Recursive=true&IncludeItemTypes=Movie,Series&SearchTerm={{ movie_title | urlencode }}&Fields=UserData&Limit=20
    method: GET
    headers:
      X-Emby-Token: !secret emby_api_key

  get_unwatched_episodes:
    url: >-
      http://192.168.1.50:8096/emby/Shows/{{ series_id }}/Episodes?IsPlayed=false&Fields=UserData&Limit=1
    method: GET
    headers:
      X-Emby-Token: !secret emby_api_key

  get_emby_movies:
    url: >-
      http://192.168.1.50:8096/emby/Items?Recursive=true&IncludeItemTypes=Movie&Fields=UserData&Limit=500
    method: GET
    headers:
      X-Emby-Token: !secret emby_api_key
```

`X-Emby-Token` можно заменить на `?api_key=` в URL — главное, чтобы скрипты получали `content.Items` с полем `UserData.PlaybackPositionTicks`.

### Скрипты

Создаются в UI (Settings → Automations & Scenes → Scripts) или YAML. Ключевые поля и действия:

**`script.emby_play_movie`** — поля `movie_title` (обязательное) и `device` (`tv` по умолчанию / `laptop`).
Порядок: включить ТВ при необходимости → `rest_command.search_emby_movie` → выбрать серию или фильм → если сериал, `rest_command.get_unwatched_episodes` → воспроизведение (ADB deep link или `play_media`) → `media_seek` → вернуть `{"message": "…"}`, который ассистент произносит дословно.

**`script.emby_list_movies`** — `rest_command.get_emby_movies` → список названий через запятую.

**`script.emby_unwatched_series`** — `rest_command.get_emby_movies` → считает сериалы с непросмотренными сериями и возвращает «Сериалов с непросмотренными сериями: N. Больше всего осталось: …».

### Скрипты (полный YAML)

<details>
<summary>Развернуть: emby_play_movie</summary>

```yaml
alias: emby_play_movie
description: Ищет фильм или сериал в Emby и запускает его на телевизоре через ADB
icon: mdi:movie-open-play
mode: queued
max: 5
fields:
  movie_title:
    name: Название
    description: Фильм или сериал, который просит пользователь
    required: true
    example: Интерстеллар
    selector:
      text: null
  device:
    name: Устройство
    description: tv — телевизор, laptop — ноутбук
    required: false
    default: tv
    selector:
      select:
        options:
        - value: tv
          label: Телевизор
        - value: laptop
          label: Ноутбук
sequence:
- variables:
    tv_entity: media_player.android_tv_192_168_1_102
    status_entity: input_text.emby_status
    query_text: '{{ movie_title | default('''', true) | trim }}'
    laptop_entity: '{{ (states.media_player | selectattr(''name'', ''equalto'', ''Ноут Asus'') | map(attribute=''entity_id'') | list | first) | default(''media_player.emby_chrome_windows_emby_chrome_windows'', true) }}'
    target_device: '{{ device | default(''tv'', true) }}'
- if:
  - condition: template
    value_template: '{{ target_device == ''tv'' and states(tv_entity) in [''off'', ''standby'', ''unavailable''] }}'
  then:
  - action: media_player.turn_on
    target:
      entity_id: '{{ tv_entity }}'
    continue_on_error: true
  - wait_template: '{{ states(tv_entity) not in [''off'', ''standby'', ''unavailable''] }}'
    timeout: 00:00:15
    continue_on_timeout: true
- if:
  - condition: template
    value_template: '{{ target_device == ''tv'' and states(tv_entity) in [''off'', ''standby'', ''unavailable''] }}'
  then:
  - variables:
      emby_reply:
        message: Телевизор не включается. Проверь питание.
  - action: input_text.set_value
    target:
      entity_id: '{{ status_entity }}'
    data:
      value: '{{ emby_reply.message }}'
    continue_on_error: true
  - stop: 'emby_play_movie: ответ сформирован'
    response_variable: emby_reply
- if:
  - condition: template
    value_template: '{{ target_device == ''laptop'' and states(laptop_entity) in [''unavailable'', ''unknown''] }}'
  then:
  - variables:
      emby_reply:
        message: Ноутбук не на связи — открой Emby на ноутбуке и повтори.
  - action: input_text.set_value
    target:
      entity_id: '{{ status_entity }}'
    data:
      value: '{{ emby_reply.message }}'
    continue_on_error: true
  - stop: 'emby_play_movie: ответ сформирован'
    response_variable: emby_reply
- action: rest_command.search_emby_movie
  data:
    movie_title: '{{ query_text }}'
  response_variable: emby_search
  continue_on_error: true
- variables:
    emby_items: "{{ emby_search.content['Items'] if (emby_search is defined\n   and emby_search.content is defined\n   and emby_search.content['Items'] is defined) else [] }}"
- variables:
    found_item: "{% set q = query_text | lower %} {% set ns = namespace(item=none, score=0) %} {% for it in emby_items %}\n  {% if (it.Type | default('')) in ['Movie', 'Series'] %}\n    {% set n = it.Name | default('') | lower %}\n    {% set s = 100 if (q and n == q) else (70 if (q and q in n) else (60 if (q and n in q) else 0)) %}\n    {% if s > ns.score %}\n      {% set ns.item = it %}\n      {% set ns.score = s %}\n    {% endif %}\n  {% endif %}\n{% endfor %} {% set fallback = (emby_items | selectattr('Type', 'in', ['Movie', 'Series']) | list | first) | default(none) %} {{ ns.item if ns.score > 0 else fallback }}"
- choose:
  - conditions:
    - condition: template
      value_template: '{{ emby_search is not defined or (emby_search.status | default(200)) >= 400 }}'
    sequence:
    - variables:
        emby_reply:
          message: Не удалось связаться с сервером Emby.
    - action: input_text.set_value
      target:
        entity_id: '{{ status_entity }}'
      data:
        value: '{{ emby_reply.message }}'
      continue_on_error: true
    - stop: 'emby_play_movie: ответ сформирован'
      response_variable: emby_reply
  - conditions:
    - condition: template
      value_template: '{{ found_item is none }}'
    sequence:
    - variables:
        emby_reply:
          message: "{{ 'Не расслышал название фильма или сериала.' if query_text == ''\n   else 'Не нашёл «' ~ query_text ~ '» в библиотеке Emby.' }}"
    - action: input_text.set_value
      target:
        entity_id: '{{ status_entity }}'
      data:
        value: '{{ emby_reply.message }}'
      continue_on_error: true
    - stop: 'emby_play_movie: ответ сформирован'
      response_variable: emby_reply
  - conditions:
    - condition: template
      value_template: '{{ found_item.Type == ''Series'' }}'
    sequence:
    - action: rest_command.get_unwatched_episodes
      data:
        series_id: '{{ found_item.Id }}'
      response_variable: emby_episodes
      continue_on_error: true
    - variables:
        first_episode: "{{ (emby_episodes.content['Items'] | first) if (emby_episodes is defined\n   and emby_episodes.content is defined\n   and emby_episodes.content['Items'] is defined\n   and emby_episodes.content['Items'] | count > 0) else none }}"
        resume_seconds: '{{ (first_episode.UserData.PlaybackPositionTicks | default(0) | int / 10000000) | round(0) }}'
    - choose:
      - conditions:
        - condition: template
          value_template: '{{ first_episode is not none }}'
        sequence:
        - if:
          - condition: template
            value_template: '{{ target_device == ''laptop'' }}'
          then:
          - action: media_player.play_media
            target:
              entity_id: '{{ laptop_entity }}'
            data:
              media_content_id: '{{ first_episode.Id }}'
              media_content_type: tvshow
          - delay:
              seconds: 1
          - if:
            - condition: template
              value_template: '{{ resume_seconds | int > 60 }}'
            then:
            - action: media_player.media_seek
              target:
                entity_id: '{{ laptop_entity }}'
              data:
                seek_position: '{{ resume_seconds }}'
              continue_on_error: true
            - delay:
                seconds: 3
            - if:
              - condition: template
                value_template: '{{ (state_attr(laptop_entity, ''media_position'') | float(0)) < (resume_seconds | int - 60) }}'
              then:
              - action: media_player.media_seek
                target:
                  entity_id: '{{ laptop_entity }}'
                data:
                  seek_position: '{{ resume_seconds }}'
                continue_on_error: true
          else:
          - action: androidtv.adb_command
            target:
              entity_id: '{{ tv_entity }}'
            data:
              command: am start -a android.intent.action.VIEW -d 'emby://play/{{ first_episode.ServerId }}/{{ first_episode.Id }}'
          - wait_template: '{{ states(''media_player.emby_gostinaia_televizor_emby_gostinaia_televizor'') in [''playing'', ''paused''] }}'
            timeout: 00:00:30
            continue_on_timeout: true
          - if:
            - condition: template
              value_template: '{{ resume_seconds | int > 60 and states(''media_player.emby_gostinaia_televizor_emby_gostinaia_televizor'') in [''playing'', ''paused''] }}'
            then:
            - action: media_player.media_seek
              target:
                entity_id: media_player.emby_gostinaia_televizor_emby_gostinaia_televizor
              data:
                seek_position: '{{ resume_seconds }}'
              continue_on_error: true
        - variables:
            emby_reply:
              message: '{{ (''Продолжаю «'' ~ found_item.Name ~ ''» с места остановки'' if resume_seconds | int > 60 else ''Включаю «'' ~ found_item.Name ~ ''»'') ~ ('' на ноутбуке.'' if target_device == ''laptop'' else '' на телевизоре.'') }}'
        - action: input_text.set_value
          target:
            entity_id: '{{ status_entity }}'
          data:
            value: '{{ emby_reply.message }}'
          continue_on_error: true
        - stop: 'emby_play_movie: ответ сформирован'
          response_variable: emby_reply
      - conditions:
        - condition: template
          value_template: '{{ emby_episodes is defined and emby_episodes.status | default(0) == 200 }}'
        sequence:
        - variables:
            emby_reply:
              message: Нет непросмотренных серий.
        - action: input_text.set_value
          target:
            entity_id: '{{ status_entity }}'
          data:
            value: '{{ emby_reply.message }}'
          continue_on_error: true
        - stop: 'emby_play_movie: ответ сформирован'
          response_variable: emby_reply
      default:
      - variables:
          emby_reply:
            message: Не удалось получить список серий из Emby.
      - action: input_text.set_value
        target:
          entity_id: '{{ status_entity }}'
        data:
          value: '{{ emby_reply.message }}'
        continue_on_error: true
      - stop: 'emby_play_movie: ответ сформирован'
        response_variable: emby_reply
  - conditions:
    - condition: template
      value_template: '{{ found_item.Type == ''Movie'' }}'
    sequence:
    - action: rest_command.get_emby_movies
      response_variable: emby_movies
      continue_on_error: true
    - variables:
        movie_resume_seconds: '{% set items = emby_movies.content[''Items''] if (emby_movies is defined and emby_movies.content is defined and emby_movies.content[''Items''] is defined) else [] %}{% set hit = items | selectattr(''Id'', ''equalto'', found_item.Id) | list | first %}{{ ((hit.UserData.PlaybackPositionTicks | default(0) | int) / 10000000) | round(0) if hit else 0 }}'
    - if:
      - condition: template
        value_template: '{{ target_device == ''laptop'' }}'
      then:
      - action: media_player.play_media
        target:
          entity_id: '{{ laptop_entity }}'
        data:
          media_content_id: '{{ found_item.Id }}'
          media_content_type: movie
      - delay:
          seconds: 1
      - if:
        - condition: template
          value_template: '{{ movie_resume_seconds | int > 60 }}'
        then:
        - action: media_player.media_seek
          target:
            entity_id: '{{ laptop_entity }}'
          data:
            seek_position: '{{ movie_resume_seconds }}'
          continue_on_error: true
        - delay:
            seconds: 3
        - if:
          - condition: template
            value_template: '{{ (state_attr(laptop_entity, ''media_position'') | float(0)) < (movie_resume_seconds | int - 60) }}'
          then:
          - action: media_player.media_seek
            target:
              entity_id: '{{ laptop_entity }}'
            data:
              seek_position: '{{ movie_resume_seconds }}'
            continue_on_error: true
      else:
      - action: androidtv.adb_command
        target:
          entity_id: '{{ tv_entity }}'
        data:
          command: am start -a android.intent.action.VIEW -d 'emby://play/{{ found_item.ServerId }}/{{ found_item.Id }}'
      - wait_template: '{{ states(''media_player.emby_gostinaia_televizor_emby_gostinaia_televizor'') in [''playing'', ''paused''] }}'
        timeout: 00:00:30
        continue_on_timeout: true
      - if:
        - condition: template
          value_template: '{{ movie_resume_seconds | int > 60 and states(''media_player.emby_gostinaia_televizor_emby_gostinaia_televizor'') in [''playing'', ''paused''] }}'
        then:
        - action: media_player.media_seek
          target:
            entity_id: media_player.emby_gostinaia_televizor_emby_gostinaia_televizor
          data:
            seek_position: '{{ movie_resume_seconds }}'
          continue_on_error: true
    - variables:
        emby_reply:
          message: '{{ (''Продолжаю «'' ~ found_item.Name ~ ''» с места остановки'' if movie_resume_seconds | int > 60 else ''Включаю «'' ~ found_item.Name ~ ''»'') ~ ('' на ноутбуке.'' if target_device == ''laptop'' else '' на телевизоре.'') }}'
    - action: input_text.set_value
      target:
        entity_id: '{{ status_entity }}'
      data:
        value: '{{ emby_reply.message }}'
      continue_on_error: true
    - stop: 'emby_play_movie: ответ сформирован'
      response_variable: emby_reply
  default:
  - variables:
      emby_reply:
        message: Не нашёл «{{ query_text }}» в библиотеке Emby.
  - action: input_text.set_value
    target:
      entity_id: '{{ status_entity }}'
    data:
      value: '{{ emby_reply.message }}'
    continue_on_error: true
  - stop: 'emby_play_movie: ответ сформирован'
    response_variable: emby_reply
```
</details>

<details>
<summary>Развернуть: emby_list_movies</summary>

```yaml
alias: emby_list_movies
sequence:
- response_variable: emby_response
  action: rest_command.get_emby_movies
- variables:
    names: '{{ emby_response.content[''Items''] | map(attribute=''Name'') | join('', '') }}'
- data:
    title: Фильмы в Emby
    message: '{{ names }}'
  action: persistent_notification.create
```
</details>

<details>
<summary>Развернуть: emby_list_movies</summary>

```yaml
alias: emby_unwatched_series
description: Считает сериалы Emby с непросмотренными сериями и показывает, где осталось больше всего
mode: single
sequence:
- action: rest_command.get_emby_movies
  response_variable: emby_all
  continue_on_error: true
- variables:
    emby_reply:
      message: '{% if emby_all is not defined or emby_all.content is not defined %}Не удалось получить данные из Emby. {% else %} {% set items = emby_all.content[''Items''] | default([]) %} {% set un = items | selectattr(''Type'', ''equalto'', ''Series'') | selectattr(''UserData.UnplayedItemCount'', ''gt'', 0) | list %} {% set multi = un | sort(attribute=''UserData.UnplayedItemCount'', reverse=true) | selectattr(''UserData.UnplayedItemCount'', ''gt'', 1) | list %} {% if un | count == 0 %}Все сериалы досмотрены. {% elif multi | count > 0 %}Сериалов с непросмотренными сериями: {{ un | count }}. Больше всего осталось: {% for it in multi[:4] %}«{{ it.Name }}» — {{ it.UserData.UnplayedItemCount }} серий{% if not loop.last %}, {% endif %}{% endfor %}. {% else %}Сериалов с непросмотренными сериями: {{ un | count }}, у каждого осталась одна серия. {% endif %} {% endif %}'
- stop: 'emby_unwatched_series: ответ сформирован'
  response_variable: emby_reply
```

</details>

### Что должно быть в EOC

Функции `play_emby_content_by_name` и `list_unfinished_series` и правила раздела 5 промпта — они уже есть в приложении (раздел 10). Ассистент передаёт `query` (только название) и `device` (`tv`/`laptop`), а ответ функции произносит символ в символ.

### Проверка

1. Settings → Devices & Services → **Emby** → в сессиях видно телевизор и ноутбук.
2. Запустить вручную: `script.emby_play_movie` с названием «Интерстеллар», device `tv` — фильм должен открыться на телевизоре.
3. В Assist: «включи Интерстеллар на телевизоре» → играет и молчит; «какие сериалы я не досмотрел» → отвечает списком.
4. Если на телевизоре не открывается — проверить ADB-соединение (`androidtv.adb_command` с `echo ok`) и что приложение Emby установлено.
