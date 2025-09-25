import os, yaml, smtplib
import requests, json, re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from kpghalogger import KpghaLogger
logger = KpghaLogger()


repo_name = os.getenv('PROJECT_GIT_REPO')
notification_map_str = os.getenv('NOTIFICATION_MAP')
app_type = os.getenv('APP_TYPE')
build_url = os.getenv('BUILD_URL')
repository_name = os.getenv('GITHUB_REPOSITORY')
org_name = os.getenv('GITHUB_REPOSITORY_OWNER')
branch_name = os.getenv('GITHUB_REF_NAME')
github_run_number = os.getenv('GITHUB_RUN_NUMBER')
github_workflow_name = os.getenv('GITHUB_WORKFLOW')
notification_flag = yaml.safe_load(os.getenv('NOTIFY_FLAGS'))
bot_deploy = os.getenv('BOT_DEPLOY')


def main():
    notification_map_str = os.getenv('NOTIFICATION_MAP')
    if not notification_map_str:
        logger.info(logger.format_msg('GHA_MSG_SENDNOTIF_BIZ_2_0001', 'No notifications configured', 'No notification map will be created'))
        return
    else:
        notification_map = yaml.safe_load(notification_map_str)
        job_status = notification_map.get('build_status') or os.getenv('JOB_STATUS')
        if notification_map.get('app_props') and notification_map.get('app_props').get('notification_map'): 
            email_recipients = notification_map['app_props'].get('notification_map').get('email_recipients')
            teams_channel = notification_map['app_props'].get('notification_map').get('teams_channel')
        else:
            email_recipients = notification_map.get('email_recipients')
            teams_channel = notification_map.get('teams_channel')
        message_body = notification_map.get('message') if notification_map.get('message') else 'Github Actions Build Status'
        message_body += f"<p>Repository Name: {repo_name}<br>Build Status: {job_status}</p><p>Pipeline Summary Link : <a href='{build_url}'>Build link</a></p>"
        if not re.match('CDO-KP-ORG|SDS', org_name):
            if bot_deploy != 'true':
                message_body += f'<p>For more details refer confluence page to view smoke/regression reports - https://confluence-aes.kp.org/pages/viewpage.action?pageId=1241387589#tab-Summary+Report</p>'
                message_body += f'<p style="color: #FF0000;">Reports will be available only for 7 days in Pipeline Summary.</p>'

        message_subject = notification_map.get('subject') if notification_map.get('subject') else f'[{repository_name}] GHA Build Status({github_run_number}) - Run {job_status} : {github_workflow_name} : {branch_name}'
        try:
            # teams webhooks and environment notifications
            if notification_flag['send-teams-notification'] == 'True':
                logger.info(f"Notify flag set to true.")
                if notification_map.get('environment_notifications') == True:
                    send_environment_notification(notification_map, job_status)
                else:            
                    notification_message(message_body, teams_channel, job_status)
                    
            # email notifications            
            send_email_notification(message_body, email_recipients, message_subject)
        except Exception as e:
            logger.error(logger.format_msg('GHA_MSG_SENDNOTIF_BIZ_4_1001', 'Error in send notification', {'detailMessage': f'Error: {e}', 'metrics': {'status': 'failure'}}))
            

def send_email_notification(message, recipients, email_subject):
    if recipients and all(isinstance(email, str) and email.strip() for email in recipients):
        logger.info(logger.format_msg('GHA_MSG_SENDNOTIF_BIZ_2_0002', 'Sending email notifications', {'detailMessage': f'Sending notifications to {recipients}', 'metrics': {'status': 'success'}}))
    else:
        logger.info(logger.format_msg('GHA_MSG_SENDNOTIF_BIZ_2_0003', 'No email notifications sent', f'No email addresses were configured'))
        return
    msg = MIMEMultipart()
    email_sender = 'githubactions@kp.org'
    msg['Subject'] = email_subject
    msg['From'] = email_sender
    msg.attach(MIMEText(message, 'html'))
    try:
        with smtplib.SMTP('mta.kp.org', 25, timeout=10) as s:
            for email_recipient in recipients:
                msg['To'] = email_recipient
                s.sendmail(from_addr=email_sender, to_addrs=email_recipient, msg=msg.as_string())
    except (TimeoutError, smtplib.SMTPException) as e:
        logger.error(f'Error while sending email notification:{e}')
    
    
def notification_message(message, teams_channel, job_status):
    if teams_channel and teams_channel != 'None':
        logger.info(logger.format_msg('GHA_MSG_SENDNOTIF_BIZ_2_0004', 'Sending MS Teams channel notification', {'detailMessage': f'Sending notifications to {teams_channel}', 'metrics': {'status': 'success'}}))
    else:
        logger.info(logger.format_msg('GHA_MSG_SENDNOTIF_BIZ_2_0005', 'No Teams notifications sent', f'No MS Teams channels configured'))
        return
    if job_status == 'success': job_color = '#00cc00'
    elif job_status == 'failure': job_color = '#ff0000'
    else: 
        job_color = '#00ff00'
        job_status = 'notify'
    headers = { 'Content-Type': 'application/json' }
    text = f"<p><strong style='color:{job_color};'>{job_status.upper()}</strong></p><p>{message}</p>"
    message_body = json.dumps({"text": text}).encode()
    post_webhook = requests.request("POST", teams_channel, data=message_body, headers=headers)
    logger.debug(logger.format_msg('GHA_MSG_SENDNOTIF_SYS_2_0001', 'Webhook content', f'{post_webhook.content}'))


def send_environment_notification(notification_map, job_status):
    try:
        deploy_env = notification_map.get('environment')
        env_notification_map = yaml.safe_load(os.getenv('ENV_NOTIFICATION_MAP'))
        teams_channel = env_notification_map.get(app_type).get(deploy_env) if env_notification_map.get(app_type) else None
        if teams_channel:
            artifact_version = notification_map.get('artifact_name')
            custom_message = notification_map.get('message') if notification_map.get('message') else ""
            message = f"Environment: <b>{deploy_env}</b>, Application Type: <b>{app_type}</b>, Artifact Version : <b>{artifact_version}, Workflow status : <b>{job_status}</b>, <b>{custom_message}</b>"
            notification_message(message, teams_channel, job_status)
    except Exception as e:
        logger.error(logger.format_msg('GHA_MSG_SENDNOTIF_BIZ_4_1002', 'Error in environment notifications', {'detailMessage': f'Error: {e}', 'metrics': {'status': 'failure'}}))


if __name__ == '__main__':
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "start"}}))
    main()
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))