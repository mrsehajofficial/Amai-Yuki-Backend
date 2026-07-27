# notifications/fcm.py
# Firebase Cloud Messaging service for Yuki backend.
# Handles all server-side push notification delivery.
#
# SETUP REQUIRED:
#   1. Place 'firebase_service_account.json' in the backend root directory.
#   2. Run: pip install firebase-admin
#   Until both are done this module silently no-ops — won't crash anything.

import os
import threading
import logging

logger = logging.getLogger(__name__)

# Lazy-initialized Firebase app — only initializes once on first use
_firebase_initialized = False
_firebase_lock = threading.Lock()
_firebase_available = False


def _init_firebase():
    """Initialize Firebase Admin SDK once. Thread-safe. Silently skips if not configured."""
    global _firebase_initialized, _firebase_available

    with _firebase_lock:
        if _firebase_initialized:
            return

        _firebase_initialized = True
        service_account_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'firebase_service_account.json'
        )

        if not os.path.exists(service_account_path):
            logger.warning(
                "FCM: firebase_service_account.json not found at %s — "
                "push notifications are disabled. See setup instructions.",
                service_account_path
            )
            return

        try:
            import firebase_admin
            from firebase_admin import credentials

            if not firebase_admin._apps:
                cred = credentials.Certificate(service_account_path)
                firebase_admin.initialize_app(cred)

            _firebase_available = True
            logger.info("FCM: Firebase Admin SDK initialized successfully.")
        except Exception as e:
            logger.error("FCM: Failed to initialize Firebase Admin SDK: %s", e)


def send_notification(fcm_token: str, title: str, body: str, data: dict = None) -> bool:
    """
    Send a push notification to a specific device FCM token.

    Args:
        fcm_token: The device's Firebase registration token.
        title:     Notification title shown in the system tray.
        body:      Notification body text.
        data:      Optional dict of string key-value pairs for deep linking.

    Returns:
        True if sent successfully, False otherwise.
    """
    _init_firebase()

    if not _firebase_available:
        return False

    if not fcm_token:
        return False

    try:
        from firebase_admin import messaging

        # Sanitize data — FCM only accepts string values
        safe_data = {str(k): str(v) for k, v in (data or {}).items()}

        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=safe_data,
            token=fcm_token,
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    channel_id='yuki_notifications',
                    click_action='FLUTTER_NOTIFICATION_CLICK',
                    sound='default',
                    default_vibrate_timings=True,
                ),
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        sound='default',
                        badge=1,
                    )
                )
            )
        )

        response = messaging.send(message)
        logger.debug("FCM: Notification sent successfully. Message ID: %s", response)
        return True

    except Exception as e:
        logger.error("FCM: Failed to send notification to token %s...: %s", fcm_token[:12], e)
        return False


def send_to_user(user_id: int, title: str, body: str, data: dict = None) -> bool:
    """
    Lookup a user's FCM token from the database and send a push notification.

    Args:
        user_id: The user's database ID.
        title:   Notification title.
        body:    Notification body.
        data:    Optional dict payload for deep-linking on the client.

    Returns:
        True if sent successfully, False if no token found or send failed.
    """
    _init_firebase()

    if not _firebase_available:
        return False

    try:
        from db.database import get_creds_db
        with get_creds_db() as conn:
            row = conn.execute(
                "SELECT fcm_token FROM users WHERE id = ?", (user_id,)
            ).fetchone()

        if not row or not row['fcm_token']:
            logger.debug("FCM: No FCM token registered for user_id=%s — skipping notification.", user_id)
            return False

        return send_notification(row['fcm_token'], title, body, data)

    except Exception as e:
        logger.error("FCM: send_to_user failed for user_id=%s: %s", user_id, e)
        return False


def send_to_users(user_ids: list, title: str, body: str, data: dict = None):
    """
    Broadcast a notification to multiple users (e.g., all active users).
    Fires each notification in the background to avoid blocking the request.
    """
    def _fire():
        for uid in user_ids:
            send_to_user(uid, title, body, data)

    threading.Thread(target=_fire, daemon=True).start()
