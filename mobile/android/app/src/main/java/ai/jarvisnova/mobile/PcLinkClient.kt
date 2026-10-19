package ai.jarvisnova.mobile

import org.json.JSONObject
import java.net.Inet4Address
import java.net.InetAddress
import java.net.URI
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/**
 * Read-only local PC status link. The user enters the certificate fingerprint
 * through a separate trusted channel. No automatic discovery, remote commands,
 * file transfer or cleartext fallback. Credentials are kept in UI RAM only.
 */
data class PcLinkConfig(val endpoint: String, val certificateSha256: String, val token: String) {
    init {
        val uri = try { URI(endpoint.trim()) } catch (_: Exception) {
            throw IllegalArgumentException("Некорректный HTTPS-адрес")
        }
        val host = uri.host ?: throw IllegalArgumentException("Нужен IPv4-адрес ПК")
        require(uri.scheme.equals("https", ignoreCase = true) &&
            uri.userInfo == null && uri.query == null && uri.fragment == null &&
            (uri.path.isNullOrEmpty() || uri.path == "/") &&
            uri.port in 1024..65535) { "Требуется HTTPS и порт 1024–65535" }
        // Numeric literals only: no DNS rebinding or accidental public network requests.
        require(Regex("""\d{1,3}(?:\.\d{1,3}){3}""").matches(host)) { "Нужен числовой IPv4-адрес" }
        val address = try { InetAddress.getByName(host) } catch (_: Exception) {
            throw IllegalArgumentException("Некорректный IPv4-адрес")
        }
        require(address is Inet4Address && (
            address.isSiteLocalAddress || address.isLoopbackAddress)) { "Разрешён только локальный IPv4" }
        require(Regex("[0-9a-fA-F]{64}").matches(certificateSha256)) {
            "Отпечаток SHA-256 должен содержать 64 hex-символа"
        }
        require(Regex("[0-9a-fA-F]{64}").matches(token)) {
            "Ключ сопряжения должен содержать 64 hex-символа"
        }
    }

    val statusUrl: String get() = endpoint.trim().trimEnd('/') + "/v1/status"
}

/** Endpoint certificate is trusted only when its exact SHA-256 matches the manually supplied pin. */
class PcLinkClient(private val config: PcLinkConfig) {
    fun checkStatus(): Boolean {
        val expected = config.certificateSha256.chunked(2)
            .map { it.toInt(16).toByte() }.toByteArray()
        val trust = object : X509TrustManager {
            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {
                throw CertificateException("Client TLS certificates are not used")
            }
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                if (chain.isEmpty()) throw CertificateException("Missing TLS certificate")
                val actual = MessageDigest.getInstance("SHA-256").digest(chain[0].encoded)
                if (!MessageDigest.isEqual(expected, actual)) {
                    throw CertificateException("PC certificate fingerprint mismatch")
                }
            }
        }
        val context = SSLContext.getInstance("TLS")
        context.init(null, arrayOf(trust), null)
        val connection = java.net.URL(config.statusUrl).openConnection() as HttpsURLConnection
        // Keep Android's default hostname verification (certificate SAN must match the entered IP).
        connection.sslSocketFactory = context.socketFactory
        connection.requestMethod = "GET"
        connection.connectTimeout = 4000
        connection.readTimeout = 4000
        connection.instanceFollowRedirects = false
        connection.setRequestProperty("Authorization", "Bearer " + config.token.lowercase())
        connection.setRequestProperty("Accept", "application/json")
        connection.useCaches = false
        return try {
            if (connection.responseCode != 200) return false
            val body = connection.inputStream.bufferedReader().use { it.readText().take(4096) }
            val state = JSONObject(body)
            state.optInt("protocol") == 1 && state.optString("status") == "online" &&
                state.optString("name") == "JARVIS NOVA PC"
        } finally {
            connection.disconnect()
        }
    }
}
