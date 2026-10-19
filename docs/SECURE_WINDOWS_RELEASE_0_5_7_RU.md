# JARVIS NOVA 0.5.7 — легальный выпуск без ложных SmartScreen / Chrome предупреждений

**Результат разработки:** CI умеет подписать офлайн-приложение и установщик
проверенным издателем через Microsoft Azure Artifact Signing, без обхода
защиты и без приватных ключей в коде. Пока Azure не настроен владельцем,
обычная CI-сборка остаётся ЧЕСТНО НЕПОДПИСАННОЙ и маркируется как DEV.

## Реализовано

- Ручной запуск GitHub Actions с sign_release=true — вход в Azure
  через OpenID Connect и подпись самого JarvisNova.exe до упаковки.
- Вторая подпись на готовом установщике Inno Setup.
- После каждой подписи запускается Windows Authenticode проверка:
  статус должен быть Valid, издатель — совпадать с настроенным и
  официально удостоверенным удостоверяющим центром.
- Подписанный выпуск при отсутствии Azure идентичности или валидной
  подписи заканчивается ошибкой и НЕ публикуется как SIGNED.
- Последний SHA256 рассчитывается после подписи; независимый Python
  скрипт проверяет SHA256SUMS.txt, имя файла, отсутствие дополнительных
  EXE и попыток подменить путь. Отдельные тесты проверяют подмену.
- Игра, камера, микрофон и разрешения JARVIS не требуют отключать Defender.

## Как включить подписание: владелец репозитория

1. В Azure создать аккаунт Artifact Signing, пройти identity validation
   и выпустить Public Trust certificate profile. Не использовать
   самоподписанные сертификаты для выпуска пользователям.
2. В Microsoft Entra настроить приложение и federated credential,
   разрешающий OIDC только GitHub репозиторию и доверенной ветке.
   Выдать минимальную роль Artifact Signing Certificate Profile Signer.
3. В GitHub: Settings → Secrets and variables → Actions добавить:
   - **Secrets**: AZURE_CLIENT_ID, AZURE_TENANT_ID,
     AZURE_SUBSCRIPTION_ID.
   - **Variables**: AZURE_SIGNING_ENDPOINT, AZURE_SIGNING_ACCOUNT,
     AZURE_SIGNING_PROFILE, AZURE_SIGNING_PUBLISHER.
     Последняя переменная — часть реального subject подтверждённого
     сертификата (не выдумывать наименование издателя).
4. В GitHub Actions выбрать JARVIS NOVA 0.5.7 Windows REAL installer.
   Выполнить Workflow dispatch с sign_release=true.
   При успехе появится артефакт с названием SIGNED; если сертификат
   невалиден, workflow должен завершиться ошибкой.
5. Публиковать через официальный GitHub Release по HTTPS, приложить
   SHA256SUMS.txt и понятный список компонентов (Whisper, Vosk,
   Silero, Ollama, FFmpeg). Пользоваться последовательной идентичностью
   издателя и не переупаковывать подписанный EXE.

Официальная документация:
- https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation
- https://github.com/Azure/artifact-signing-action
- https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect
- https://support.google.com/chrome/answer/6261569

## Как пользователю проверить скачанный файл

В PowerShell:
- Get-AuthenticodeSignature путь_к_установщику.exe
- Get-FileHash путь_к_установщику.exe -Algorithm SHA256

Проверить, что подпись — Valid, издатель соответствует ожидаемому,
а SHA256 совпадает с хешем, опубликованным в GitHub Release.

Если Microsoft Defender ошибочно обнаружил безопасный релиз:
https://www.microsoft.com/en-us/wdsi/filesubmission — отправить точный
файл на ручной анализ как разработчик, затем дождаться решения.

**Нельзя гарантировать отсутствие предупреждений:** SmartScreen строит
репутацию издателя и хеша по истории безопасных загрузок, а Chrome может
предупреждать о редких EXE независимо от Windows. Подпись не означает
отсутствия уязвимостей и не заменяет анализ зависимостей.
Не просите пользователей отключать Defender/SmartScreen/Safe Browsing,
добавлять исключения в антивирус или принудительно запускать подозрительный файл.
