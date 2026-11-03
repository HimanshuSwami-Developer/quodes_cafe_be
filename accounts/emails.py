from quodes import mailer

from .models import OneTimeCode

COPY = {
    OneTimeCode.Purpose.VERIFY_EMAIL: ("Confirm your email", "Confirm your email",
                                       "Enter this code in the Quodes app to activate your account."),
    OneTimeCode.Purpose.RESET_PASSWORD: ("Your password reset code", "Reset your password",
                                         "Enter this code in the Quodes app to set a new password."),
}


def send_code(user, purpose):
    _, code = OneTimeCode.issue(user, purpose)
    subject, heading, intro = COPY[purpose]
    mailer.send(user.email, f"{code} is your code", "otp", {
        "code": code, "heading": heading, "intro": intro,
        "minutes": int(OneTimeCode.LIFETIME.total_seconds() // 60)}, now=True)
