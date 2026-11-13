name: Оновлення розкладу електричок

on:
  schedule:
    # Запуск щодня о 03:30 за UTC (05:30 або 06:30 за Києвом)
    - cron: '30 3 * * *'
  workflow_dispatch: # Дозволяє запустити скрипт вручну кнопкою на GitHub

permissions:
  contents: write # Дозвіл боту зберігати оновлений schedule.json

jobs:
  update-schedule:
    runs-on: ubuntu-latest
    env:
      TZ: Europe/Kyiv # Важливо, щоб date.today() брав київську дату

    steps:
      - name: Завантаження коду репозиторію
        uses: actions/checkout@v4

      - name: Налаштування Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Встановлення бібліотек
        run: pip install requests beautifulsoup4

      - name: Запуск парсера
        run: python update.py

      - name: Збереження оновленого файлу
        run: |
          git config --local user.email "github-actions[bot]@://github.com"
          git config --local user.name "github-actions[bot]"
          git add schedule.json
          git diff --quiet && git diff --staged --quiet || (git commit -m "Оновлення розкладу" && git push)
          
