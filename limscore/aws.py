import boto3
from botocore.exceptions import ClientError
from flask import current_app
from werkzeug.exceptions import InternalServerError

from .i18n import _

def sendmail(recipients, subject, body):
    config = current_app.config
    
    try:
        sender = config["MAIL_SENDER"]
        region = config["MAIL_REGION"]
    except KeyError:
        raise InternalServerError(_("Unable to send email. Please contact an administrator."))
    
    if isinstance(recipients, str):
        recipients = recipients.split(",")

    client = boto3.client('ses', region_name=region)

    try:
        response = client.send_email(
            Destination={'ToAddresses': recipients,
                        },
            Message={'Body': {'Text': {'Charset': "UTF-8",
                                       'Data': body,
                                      },
                             },
                     'Subject': {'Charset': "UTF-8",
                                 'Data': subject,
                                },
                    },
            Source=sender,
            )
    	
    except ClientError as e:
        raise InternalServerError(_("Unable to send email at the present time. Please contact an administrator if this problem persists."))
    
