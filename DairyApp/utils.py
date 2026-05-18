import africastalking
import qrcode
from io import BytesIO

from django.conf import settings
from django.core.mail import send_mail
from django.core.files.base import ContentFile


def send_sms_alert(message):
    try:
        africastalking.initialize(
            settings.AFRICASTALKING_USERNAME,
            settings.AFRICASTALKING_API_KEY
        )

        sms = africastalking.SMS
        sms.send(message, [settings.ALERT_PHONE_NUMBER])

    except Exception as e:
        print("SMS error:", e)


def send_email_alert(subject, message):
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [settings.ALERT_EMAIL],
            fail_silently=False,
        )

    except Exception as e:
        print("Email error:", e)


def generate_fridge_qr(fridge):
    qr_text = f"DAIRYSYNC FRIDGE\nCode: {fridge.fridge_code}\nInstitution: {fridge.institution.name}"

    image = qrcode.make(qr_text)

    buffer = BytesIO()
    image.save(buffer, format="PNG")

    filename = f"{fridge.fridge_code}_qr.png"

    fridge.qr_code.save(filename, ContentFile(buffer.getvalue()), save=True)