package ai.jarvisnova.mobile

import org.junit.Assert.*
import org.junit.Test

class PcLinkConfigTest {
    private val pin = "a".repeat(64)
    private val token = "b".repeat(64)

    @Test fun acceptsPrivateHttpsIpv4Only() {
        val link = PcLinkConfig("https://192.168.1.50:8443", pin, token)
        assertEquals("https://192.168.1.50:8443/v1/status", link.statusUrl)
        assertEquals("https://10.0.0.2:9443/v1/status",
            PcLinkConfig("https://10.0.0.2:9443/", pin, token).statusUrl)
    }

    @Test fun refusesCleartextExternalAndUrlManipulation() {
        for (endpoint in listOf(
            "http://192.168.1.50:8443",
            "https://example.com:8443",
            "https://8.8.8.8:8443",
            "https://192.168.1.50:8443/extra",
            "https://user@192.168.1.50:8443",
            "https://192.168.1.50:8443/?token=secret",
            "https://0.0.0.0:8443"
        )) {
            try {
                PcLinkConfig(endpoint, pin, token)
                fail("Should refuse endpoint: $endpoint")
            } catch (_: IllegalArgumentException) {}
        }
    }

    @Test fun demandsFull256BitPinAndSecret() {
        for ((fingerprint, secret) in listOf(
            Pair("a", token), Pair(pin, "short"), Pair("g".repeat(64), token),
            Pair(pin, "x".repeat(64))
        )) {
            try {
                PcLinkConfig("https://172.16.2.10:8443", fingerprint, secret)
                fail("Should reject short or non-hex credentials")
            } catch (_: IllegalArgumentException) {}
        }
    }
}
