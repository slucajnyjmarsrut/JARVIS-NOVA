# JARVIS NOVA PYAGENT RC3 — технический статус

Дата: 2026-10-16

**Сборка EXE: НЕ ПРОВЕДЕНА.** Здесь Linux, Windows-PyInstaller недоступен,
а DNS для PyPI и моделей недоступен. ZIP является исходным проектом,
не установочным Windows приложением.

Изменения:
1. Ранний `multiprocessing.freeze_support()`.
2. Запуск Vosk до загрузки Silero.
3. `bootstrap.py --self-test` для проверки уже упакованного EXE.
4. GitHub Actions проверяет EXE в Windows после упаковки.
5. 31 тест Python прошёл; проверен синтаксис исходников.
6. Закрытие по X сохранено из RC2; фоновые потоки прекращают работу.
7. Исходники Whisper из загруженного ZIP не являются самими весами.
8. Загруженный SileroTTS_Ru_Setup не запускался и не встраивался.

Что *не* сделано: полноценная Windows PyInstaller сборка, проверка
микрофона и ASR/озвучки на Windows, локальная встроенная модель зрения,
полностью автономный AI в любых программах, Android APK.

Для получения EXE используйте `.github/workflows/build-exe.yml`
на собственном Windows GitHub Actions раннере.
