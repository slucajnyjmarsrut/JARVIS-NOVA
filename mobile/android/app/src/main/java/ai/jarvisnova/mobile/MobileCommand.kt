package ai.jarvisnova.mobile

/** Pure, deterministic parser: neither speech recognition nor AI may create shell commands. */
sealed interface MobileCommand {
    data class DialContact(val name: String) : MobileCommand
    data object PlayMusic : MobileCommand
    data object PauseMusic : MobileCommand
    data object NextTrack : MobileCommand
    data object PreviousTrack : MobileCommand
    data object Help : MobileCommand
    data object Unknown : MobileCommand
}

object MobileCommandParser {
    private val wake = Regex("""^(?:джарвис|jarvis)[,!\s.]*""", RegexOption.IGNORE_CASE)
    private val dial = Regex("""^(?:позвони|набери)\s+(?:контакту\s+)?(.+)$""", RegexOption.IGNORE_CASE)
    private val safeContact = Regex("""^[\p{L}][\p{L}\p{N} .'-]{0,63}$""")
    fun parse(utterance: String): MobileCommand {
        val normalized = wake.replaceFirst(utterance.trim(), "").trim().lowercase()
        val contact = dial.matchEntire(normalized)?.groupValues?.getOrNull(1)?.trim()
        if (contact != null) {
            return if (safeContact.matches(contact) && contact.none { it == '\n' || it == '\r' })
                MobileCommand.DialContact(contact) else MobileCommand.Unknown
        }
        return when (normalized) {
            "включи музыку", "играй музыку", "воспроизведи музыку", "продолжи музыку" -> MobileCommand.PlayMusic
            "пауза", "останови музыку", "поставь на паузу" -> MobileCommand.PauseMusic
            "следующий трек", "следующая песня", "переключи трек" -> MobileCommand.NextTrack
            "предыдущий трек", "предыдущая песня" -> MobileCommand.PreviousTrack
            "помощь", "команды", "что ты умеешь" -> MobileCommand.Help
            else -> MobileCommand.Unknown
        }
    }
}
