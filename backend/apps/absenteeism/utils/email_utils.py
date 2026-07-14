import base64
import logging
from datetime import datetime
from django.conf import settings
from django.template.loader import render_to_string
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition

logger = logging.getLogger('general')

def send_email(recipient_emails, data, subject, type, file_name, test=False, encoded_data=None):
    try:
        logger.info(f"*******************************************************************")
        logger.info(f"Running EMAIL FUNCTION at {str(datetime.now())} hours!")
        # Get today's date
        # Render the email body from the template
        email_body = render_to_string('absenteeism_export.html', {'subject': subject})

        # SendGrid API configuration
        sendgrid_api_key = settings.SENDGRID_API_KEY
        sendgrid_from_email = settings.DEFAULT_FROM_EMAIL

        # Ensure recipient_emails is a list
        if isinstance(recipient_emails, str):
            recipient_emails = recipient_emails.split(',')  # Split comma-separated string into a list

        # Create the Mail object
        message = Mail(
            from_email=sendgrid_from_email,
            to_emails=recipient_emails,  # Pass the list of email addresses
            subject=subject,
            html_content=email_body,
        )

        attachments_list = []

        # Add attachment if data is provided
        if data or encoded_data:
            # Base64 encode the file (SendGrid requires this format)
            if not encoded_data:
                encoded_data = base64.b64encode(data.getvalue()).decode()

            # Create the attachment
            attached_file = Attachment(
                file_content=FileContent(encoded_data),
                file_name=FileName(file_name),
                file_type=FileType(type),
                disposition=Disposition('attachment')
            )
            # message.attachment = attached_file
            attachments_list.append(attached_file)

        if test:
            with open('csv_files/attendance.csv', 'rb') as f:
                encoded_csv = base64.b64encode(f.read()).decode()
                attached_file_2 = Attachment(
                    file_content=FileContent(encoded_csv),
                    file_name=FileName("attendance.csv"),
                    file_type=FileType("text/csv"),
                    disposition=Disposition('attachment')
                )
                attachments_list.append(attached_file_2)

        message.attachment = attachments_list

        # Send the email
        sg = SendGridAPIClient(sendgrid_api_key)
        response = sg.send(message)
        logger.info(f"Response status code {response.status_code}!")

        # Check for successful response
        if response.status_code in [200, 202]:
            return email_body
        else:
            logger.info(f"Error sending email: {response.status_code}, {response.body}")
            return None

    except Exception as e:
        logger.info(f"Error sending email: {e}")
        return None
