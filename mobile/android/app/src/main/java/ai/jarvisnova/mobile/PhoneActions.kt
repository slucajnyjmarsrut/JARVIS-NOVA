package ai.jarvisnova.mobile

import android.Manifest
import android.app.Activity
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.net.Uri
import android.provider.ContactsContract
import android.provider.Settings
import android.widget.AlertDialog

class PhoneActions(private val activity: Activity, private val feedback: (String) -> Unit) {
    fun dialContact(name: String) {
        if (activity.checkSelfPermission(Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) {
            feedback("Для звонка разреши JARVIS доступ к контактам.")
            activity.requestPermissions(arrayOf(Manifest.permission.READ_CONTACTS), REQUEST_CONTACTS)
            return // Do not place a call until the user repeats the command after granting access.
        }
        val matches = mutableListOf<Pair<String, String>>()
        val resolver = activity.contentResolver
        val display = ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME
        val number = ContactsContract.CommonDataKinds.Phone.NUMBER
        resolver.query(
            ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
            arrayOf(display, number),
            "$display = ?", arrayOf(name), "$display ASC"
        )?.use { cursor ->
            val nameIndex = cursor.getColumnIndexOrThrow(display)
            val numberIndex = cursor.getColumnIndexOrThrow(number)
            while (cursor.moveToNext() && matches.size < 20) {
                val label = cursor.getString(nameIndex) ?: continue
                val phone = cursor.getString(numberIndex) ?: continue
                if (label.equals(name, ignoreCase = true) && phone.isNotBlank()) {
                    matches.add(label to phone)
                }
            }
        }
        val distinct = matches.distinctBy { it.second }
        when (distinct.size) {
            0 -> feedback("Контакт не найден. Уточни его имя в телефонной книге.")
            1 -> openSystemDialer(distinct.first().second)
            else -> AlertDialog.Builder(activity)
                .setTitle("Какой номер контакта использовать?")
                .setItems(distinct.map { it.first + " • " + it.second.takeLast(4) }.toTypedArray()) { _, which ->
                    openSystemDialer(distinct[which].second)
                }
                .setNegativeButton("Отмена", null)
                .show()
        }
    }

    private fun openSystemDialer(number: String) {
        // ACTION_DIAL is intentional: no silent outbound calls, no CALL_PHONE permission,
        // no attempted bypass of the lock screen or system confirmation.
        val intent = Intent(Intent.ACTION_DIAL, Uri.fromParts("tel", number, null))
        try {
            activity.startActivity(intent)
            feedback("Номер готов в системной звонилке. Подтверди вызов.")
        } catch (_: Exception) {
            feedback("Системная звонилка недоступна. Разблокируй устройство при необходимости.")
        }
    }

    fun music(command: MobileCommand) {
        val manager = activity.getSystemService(MediaSessionManager::class.java)
        val sessions = try {
            manager.getActiveSessions(ComponentName(activity, JarvisNotificationListener::class.java))
        } catch (_: SecurityException) {
            feedback("Для управления плеером включи JARVIS в настройках доступа к уведомлениям.")
            activity.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
            return
        }
        val selected = sessions.firstOrNull { it.playbackState?.state == PlaybackState.STATE_PLAYING }
            ?: sessions.firstOrNull()
        if (selected == null) {
            feedback("Сейчас нет доступного активного плеера. Открой музыку один раз в своём приложении.")
            return
        }
        try {
            when (command) {
                MobileCommand.PlayMusic -> selected.transportControls.play()
                MobileCommand.PauseMusic -> selected.transportControls.pause()
                MobileCommand.NextTrack -> selected.transportControls.skipToNext()
                MobileCommand.PreviousTrack -> selected.transportControls.skipToPrevious()
                else -> return
            }
            feedback("Команда отправлена музыкальному плееру.")
        } catch (_: Exception) {
            feedback("Плеер не разрешил выполнить команду.")
        }
    }

    companion object { const val REQUEST_CONTACTS = 123 }
}
