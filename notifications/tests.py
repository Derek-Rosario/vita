from django.test import TestCase, override_settings
from unittest.mock import patch, MagicMock
from notifications.emails import (
    send_mail,
    send_morning_report_email,
    MorningReportEmailArgs,
)


class SendMailTestCase(TestCase):
    @override_settings(
        RESEND_SMTP_HOST="smtp.example.com",
        RESEND_SMTP_PORT=587,
        RESEND_SMTP_USERNAME="test_user",
        DEFAULT_FROM_EMAIL="noreply@example.com",
    )
    @patch.dict("os.environ", {"RESEND_API_KEY": "test_api_key"})
    @patch("notifications.emails.emails.get_connection")
    @patch("notifications.emails.emails.EmailMessage")
    def test_send_mail_success(self, mock_email_message, mock_get_connection):
        # Arrange
        mock_connection = MagicMock()
        mock_get_connection.return_value.__enter__.return_value = mock_connection
        mock_email_instance = MagicMock()
        mock_email_instance.send.return_value = 1
        mock_email_message.return_value = mock_email_instance

        # Act
        result = send_mail(
            to_address="test@example.com",
            subject="Test Subject",
            body="Test Body",
        )

        # Assert
        mock_get_connection.assert_called_once_with(
            host="smtp.example.com",
            port=587,
            username="test_user",
            password="test_api_key",
            use_tls=True,
        )
        mock_email_message.assert_called_once_with(
            subject="Test Subject",
            body="Test Body",
            to=["test@example.com"],
            from_email="noreply@example.com",
            connection=mock_connection,
        )
        mock_email_instance.send.assert_called_once()
        self.assertEqual(result, 1)


class SendMorningReportEmailTestCase(TestCase):
    @override_settings(SELF_EMAIL="user@example.com")
    @patch("notifications.emails.emails.send_mail")
    @patch("notifications.emails.emails.mjml_to_html")
    @patch("notifications.emails.emails.render_to_string")
    def test_send_morning_report_email(
        self, mock_render_to_string, mock_mjml_to_html, mock_send_mail
    ):
        # Arrange
        mock_render_to_string.return_value = "<mjml>mock content</mjml>"
        mock_mjml_to_html.return_value = "<html>mock html</html>"
        mock_send_mail.return_value = 1

        args = MorningReportEmailArgs(
            in_progress_count=5,
            in_progress_points=13,
            yesterday_comparison="up",
            yesterday_in_progress_count=3,
            yesterday_in_progress_points=8,
            in_progress_tasks=[],
        )

        # Act
        result = send_morning_report_email(args)

        # Assert
        mock_render_to_string.assert_called_once_with(
            "templates/emails/morning_report.html",
            context={
                "in_progress_count": 5,
                "in_progress_points": 13,
                "yesterday_comparison": "up",
                "yesterday_in_progress_count": 3,
                "yesterday_in_progress_points": 8,
                "in_progress_tasks": [],
            },
        )
        mock_mjml_to_html.assert_called_once_with("<mjml>mock content</mjml>")
        mock_send_mail.assert_called_once_with(
            to_address="user@example.com",
            subject="Your Morning Report",
            body="<html>mock html</html>",
        )
        self.assertEqual(result, 1)
