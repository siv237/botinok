---
type: source
tags: [config]
updated: 2026-08-23
sources: 1
status: stable
---

# config.cfg

Файл конфигурации по умолчанию (корень репо). Source: `<repo>/config.cfg`. → `entities/config_system.md`, `concepts/config_priority.md`

## Секции и ключи (фактические значения из файла)
**`[Ollama]`**
- `baseurl = http://localhost:11434`
- `defaultmodel = qwen3.5:9b`
- `defaultcontext = 16384`
- `requesttimeout = 300`
- `temperature = 0.1` · `top_p = 0.9` · `top_k = 40` · `repeat_penalty = 1.1` · `num_predict = 4096`
- (в коде также: `backend` — значение `ollama`/`openai`, `verify_ssl`)

**`[Storage]`**
- `sessionsdir = sessions` · `stepssubdir = steps`

**`[Tools]`**
- `lynxuseragent = Mozilla/5.0 (Compatible; Lynx/2.8.9rel.1; Linux)` · `lynxmaxchars = 8000` · `lynxconnecttimeout = 10` · `lynxreadtimeout = 15`

**`[UI]`**
- `showvram = true` · `showtps = true`

## Примечание
Конфиг в `.gitignore` — локальные значения не коммитятся (файл может перекрываться локальным/личным/системным). → `concepts/config_priority.md`
