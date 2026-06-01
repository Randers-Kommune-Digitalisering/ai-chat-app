import utils.mail_client as mail_client


def test_build_sender_appends_randers_domain_when_missing(monkeypatch):
    monkeypatch.setattr(mail_client, "FEEDBACK_SMTP_SENDER_NAME", "Test Sender")
    monkeypatch.setattr(mail_client, "FEEDBACK_SMTP_SENDER_EMAIL", "some.user")

    sender = mail_client._build_sender()

    assert sender == ("Test Sender", "some.user@randers.dk")


def test_build_sender_does_not_change_email_when_domain_present(monkeypatch):
    monkeypatch.setattr(mail_client, "FEEDBACK_SMTP_SENDER_NAME", "Test Sender")
    monkeypatch.setattr(mail_client, "FEEDBACK_SMTP_SENDER_EMAIL", "some.user@example.com")

    sender = mail_client._build_sender()

    assert sender == ("Test Sender", "some.user@example.com")


def test_build_sender_appends_domain_when_trailing_at(monkeypatch):
    monkeypatch.setattr(mail_client, "FEEDBACK_SMTP_SENDER_NAME", None)
    monkeypatch.setattr(mail_client, "FEEDBACK_SMTP_SENDER_EMAIL", "some.user@")

    sender = mail_client._build_sender()

    assert sender == "some.user@randers.dk"


def test_build_recipients_appends_randers_domain_when_missing(monkeypatch):
    monkeypatch.setattr(mail_client, "FEEDBACK_MAIL_RECIPIENT", ["user.one", "user.two@example.com"])

    recipients = mail_client._build_recipients()

    assert recipients == ["user.one@randers.dk", "user.two@example.com"]


def test_build_recipients_appends_domain_when_trailing_at(monkeypatch):
    monkeypatch.setattr(mail_client, "FEEDBACK_MAIL_RECIPIENT", ["some.user@"])

    recipients = mail_client._build_recipients()

    assert recipients == ["some.user@randers.dk"]
