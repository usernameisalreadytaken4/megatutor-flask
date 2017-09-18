from flask_mail import Message
from app import mail, app
from flask import render_template
from config import ADMINS
# from decorators import async - дерьмо мамонта, но актуально для 2.7 наверно.

# на винде нихера не отправляет, ошибка winerror
# более чем уверен, что на линуксе все норм, с джанго же работало
# так что винда говно и не пишите веб приложения на винде
# а лучше, никакие приложения на винде не пишите


def send_email(subject, sender, recipients, text_body, html_body):
    msg = Message(subject=subject, sender=sender, recipients=recipients)
    msg.body = text_body
    msg.html = html_body
    send_async_email(app, msg)


async def send_async_email(app, msg):
    with app.app_context():
        mail.send(msg)


def follower_notification(followed, follower):
    send_email(f'[microblog] {follower.nickname}', ADMINS[0], [followed.email],
               render_template('follower_email.txt', user=followed, follower=follower),
               render_template('follower_email.html', user=followed, follower=follower))