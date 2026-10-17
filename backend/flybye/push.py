"""Push through Firebase Cloud Messaging to every device the app has registered."""
from firebase_admin import exceptions, messaging

DEAD = (messaging.UnregisteredError, exceptions.InvalidArgumentError)  # the token will never work again


def send(st, title, body, data=None, link=None, fan=messaging.send_each):
    tokens = st.device_tokens()
    if not tokens:
        return
    web = messaging.WebpushConfig(fcm_options=messaging.WebpushFCMOptions(link=link)) if link else None
    msgs = [messaging.Message(token=t, notification=messaging.Notification(title=title, body=body),
                              data=data or {}, webpush=web) for t in tokens]
    for t, r in zip(tokens, fan(msgs).responses):
        if not r.success and isinstance(r.exception, DEAD):
            st.drop_token(t)
