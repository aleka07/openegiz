# Contributing to OpenEgiz

*Русская версия — ниже.*

Thanks for helping. Bug reports, fixes, docs and new examples are all welcome.

## Reporting a bug

Open an issue with the **Bug report** template. The two things that make a report fixable:

- what you ran and what happened, with the error text (not a screenshot of it);
- your environment: OS, CPU architecture, `docker version`, `docker compose version`, and the output of `make ps`.

**Remove passwords before you paste logs.** `make up` prints the generated credentials, and `deploy/compose/.env` holds them.

## Security issues

Do not open a public issue for a vulnerability. Use **Security → Report a vulnerability** on GitHub; the report stays private until it is fixed.

## Making a change

1. Fork, branch from `main`.
2. Run the stack and the end-to-end check before and after your change:

   ```bash
   make up
   make example-mine
   make smoke
   ```

3. Keep the change focused: one fix or feature per pull request. If it changes how people install or use the platform, update both `README.md` and `README.ru.md`.
4. Open the pull request. CI runs lint and brings up the full stack with the Example Mine on amd64 and arm64; it has to be green.

Never commit `deploy/compose/.env`, `secrets.values.yaml` or any real credential.

## License of contributions

OpenEgiz's own code is MIT; parts derived from OpenTwins stay under Apache-2.0 (see [NOTICE](NOTICE)). By opening a pull request you agree that your contribution is released under the license of the files it changes.

---

# Как помочь OpenEgiz

**Нашли баг** — откройте issue по шаблону **Bug report**: что запускали, что произошло (текст ошибки, не скриншот), ОС, архитектура, `docker version`, `docker compose version`, вывод `make ps`. **Перед тем как вставлять логи, уберите из них пароли**: `make up` их печатает, а хранятся они в `deploy/compose/.env`.

**Уязвимость** — не в публичный issue, а через **Security → Report a vulnerability** на GitHub.

**Хотите прислать правку** — форк, ветка от `main`, до и после изменений прогоните `make up`, `make example-mine`, `make smoke`. Один PR — одно изменение. Если меняется установка или использование — обновите и `README.md`, и `README.ru.md`. CI (lint + полный стек с Примером рудника на amd64 и arm64) должен быть зелёным. Файлы с паролями (`deploy/compose/.env`, `secrets.values.yaml`) не коммитьте.

Собственный код OpenEgiz — MIT, производные от OpenTwins части — Apache-2.0 (см. [NOTICE](NOTICE)). Открывая PR, вы соглашаетесь, что ваш вклад выходит под лицензией файлов, которые он меняет.
