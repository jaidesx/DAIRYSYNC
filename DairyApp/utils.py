import logging
import qrcode
from io import BytesIO

import africastalking
from django.conf import settings
from django.core.mail import send_mail, send_mass_mail
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)


def send_sms_alert(message, recipients=None):
    try:
        africastalking.initialize(
            settings.AFRICASTALKING_USERNAME,
            settings.AFRICASTALKING_API_KEY,
        )
        phones = recipients if recipients else [settings.ALERT_PHONE_NUMBER]
        phones = [p for p in phones if p]
        if not phones:
            return
        africastalking.SMS.send(message, phones)
    except Exception:
        logger.exception('SMS alert failed')


def send_email_alert(subject, message, recipient=None, recipients=None):
    """
    Send an alert email to one or more addresses.

    Pass `recipient` (single str) or `recipients` (list of str).
    Falls back to settings.ALERT_EMAIL when neither is supplied.
    Uses send_mass_mail when multiple addresses are given so each
    recipient gets an individual message (no CC leakage).
    """
    try:
        if recipients:
            targets = [r for r in recipients if r]
        elif recipient:
            targets = [recipient]
        else:
            targets = [settings.ALERT_EMAIL] if getattr(settings, 'ALERT_EMAIL', '') else []

        if not targets:
            return

        from_email = settings.DEFAULT_FROM_EMAIL
        if len(targets) == 1:
            send_mail(subject, message, from_email, targets, fail_silently=False)
        else:
            datatuple = tuple(
                (subject, message, from_email, [addr]) for addr in targets
            )
            send_mass_mail(datatuple, fail_silently=False)
    except Exception:
        logger.exception('Email alert failed')


def generate_fridge_qr(fridge):
    qr_text = f"DAIRYSYNC FRIDGE\nCode: {fridge.fridge_code}\nInstitution: {fridge.institution.name}"
    image = qrcode.make(qr_text)
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    filename = f"{fridge.fridge_code}_qr.png"
    fridge.qr_code.save(filename, ContentFile(buffer.getvalue()), save=True)
