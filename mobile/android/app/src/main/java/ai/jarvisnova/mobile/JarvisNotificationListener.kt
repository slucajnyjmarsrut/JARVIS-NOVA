package ai.jarvisnova.mobile

import android.service.notification.NotificationListenerService

/**
 * Required by Android to obtain MediaSessionManager's active-session list,
 * only after the owner explicitly enables notification access in Settings.
 * Do NOT capture, store or forward notifications.
 */
class JarvisNotificationListener : NotificationListenerService()
