package ai.jarvisnova.mobile

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.os.Bundle
import android.speech.RecognizerIntent
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/** MVP: voice via explicit system microphone dialog, not an always-listening locked-screen assistant. */
class MainActivity : Activity() {
    private lateinit var text: EditText
    private lateinit var message: TextView
    private lateinit var phone: PhoneActions

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        phone = PhoneActions(this) { report(it) }
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(28, 28, 28, 28)
        }
        layout.addView(TextView(this).apply {
            text = "JARVIS NOVA Mobile — ранний прототип"
            textSize = 23f
        })
        layout.addView(TextView(this).apply {
            text = "Звонок открывает системную звонилку. Музыка управляется через разрешённую медиасессию. " +
                "Голос работает после нажатия кнопки; непрерывный вызов с заблокированного экрана ещё не реализован."
        })
        text = EditText(this).apply { hint = "Например: Джарвис, позвони маме" }
        layout.addView(text)
        layout.addView(Button(this).apply {
            this.text = "Выполнить команду"
            setOnClickListener { execute(text.text.toString()) }
        })
        layout.addView(Button(this).apply {
            this.text = "Сказать голосом"
            setOnClickListener { requestSpeech() }
        })
        message = TextView(this).apply { textSize = 16f }
        layout.addView(message)
        val scroll = ScrollView(this)
        scroll.addView(layout)
        setContentView(scroll)
        report("Готов к команде.")
    }

    private fun report(value: String) { message.text = value }

    private fun execute(utterance: String) {
        when (val command = MobileCommandParser.parse(utterance)) {
            is MobileCommand.DialContact -> phone.dialContact(command.name)
            MobileCommand.PlayMusic, MobileCommand.PauseMusic,
            MobileCommand.NextTrack, MobileCommand.PreviousTrack -> phone.music(command)
            MobileCommand.Help -> report("Скажи: позвони <имя>, включи музыку, пауза, следующий или предыдущий трек.")
            MobileCommand.Unknown -> report("Команда пока не поддерживается. Скажи «команды».")
        }
    }

    private fun requestSpeech() {
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ru-RU")
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            putExtra(RecognizerIntent.EXTRA_PROMPT, "Скажи команду JARVIS")
        }
        try {
            startActivityForResult(intent, VOICE_REQUEST)
        } catch (_: ActivityNotFoundException) {
            report("В системе нет приложения распознавания речи. Можно набрать команду текстом.")
        }
    }

    @Deprecated("Uses platform result API without AndroidX for lightweight MVP")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == VOICE_REQUEST && resultCode == RESULT_OK) {
            val heard = data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
                ?.firstOrNull()?.take(200) ?: return
            text.setText(heard)
            execute(heard)
        }
    }

    companion object { const val VOICE_REQUEST = 42 }
}
