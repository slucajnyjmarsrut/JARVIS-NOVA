package ai.jarvisnova.mobile

import org.junit.Assert.*
import org.junit.Test

class MobileCommandParserTest {
    @Test fun callsOnlyNamedContacts() {
        assertEquals(MobileCommand.DialContact("маме"), MobileCommandParser.parse("Джарвис, позвони маме"))
        assertEquals(MobileCommand.DialContact("анна"), MobileCommandParser.parse("Позвони контакту Анна"))
    }
    @Test fun musicPhrases() {
        assertEquals(MobileCommand.PlayMusic, MobileCommandParser.parse("джарвис включи музыку"))
        assertEquals(MobileCommand.PauseMusic, MobileCommandParser.parse("Пауза"))
        assertEquals(MobileCommand.NextTrack, MobileCommandParser.parse("Следующий трек"))
        assertEquals(MobileCommand.PreviousTrack, MobileCommandParser.parse("Предыдущий трек"))
    }
    @Test fun rejectDangerousOrUnclearInput() {
        for (phrase in listOf("позвони https://evil.example", "позвони 123456", "позвони cmd /c del", "удали всё")) {
            assertEquals(MobileCommand.Unknown, MobileCommandParser.parse(phrase))
        }
    }
    @Test fun wakeAndUnknown() {
        assertEquals(MobileCommand.Help, MobileCommandParser.parse("Джарвис! команды"))
        assertEquals(MobileCommand.Unknown, MobileCommandParser.parse(""))
    }
}
