import os

from smtplib import SMTP, SMTPException
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.utils import formatdate

__all__ = ("MailServer",)

class MailServer(object):
    
    def __init__(self, tls=True, **kwargs):
        """Connects to SMTP server.

        Args:
            tls (bool): Put the SMTP connection in TLS mode if True.
            kwargs (dict): Must contain username and smtp_url, may contain password and return_to.
            
        Returns:
            None.
            
        Raises:
            RuntimeError if username or smtp_url missing
            SMTPAuthenticationError if password incorrect.
            SMTPException for everything else
        """
        self.server = SMTP()
        try:
            self.username = kwargs["username"]
            self.server.connect(kwargs["smtp_url"])
        except KeyError:
            raise RuntimeError("Mailserver details missing from database.")
            
        self.reply_to = kwargs.get("reply_to", None)
        if tls: 
            self.server.starttls()
        if kwargs["password"]:
            self.server.login(self.username, kwargs["password"])

    
    def __enter__(self):
        return self

        
    def __exit__(self, tp, value, tb):
        self.close()

        
    def close(self):
        self.server.quit()

        
    def send(self, recipients, subject, body, attachments=()):
        """Sends a single email message.

        Args:
            recipients (string or list of stings): List of message recipients, either as a comma separated string or a list of strings.
            subject (string): Message subject.
            body (string): Message body.
            attachments (list): List of filename, content pairs (only .txt and .pdf filetypes supported).
            
        Returns:
            None.
            
        Raises:
            SMTPException
            RuntimeError if attachment is not .txt or .pdf
        """
        if isinstance(recipients, str):
            recipients = recipients.split(",")
        
        msg = MIMEMultipart()
        msg["From"] = self.username
        msg["To"] = ",".join(recipients)
        msg["Date"] = formatdate(localtime=True)
        msg["Subject"] = subject
        if self.reply_to:
            msg.add_header("reply-to", self.reply_to)
        msg.attach(MIMEText(body))

        for filename, content in attachments:
            extension = os.path.splitext(filename)[1]
            if extension == ".txt":
                attachment = MIMEText(content)
            elif extension == ".pdf":
                    attachment = MIMEApplication(content)
            else:
                raise RuntimeError("Unknown email attachment type {}.".format(extension))
            attachment.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(attachment)

        server.send_message(msg, self.username, recipients + [self.username])
        
