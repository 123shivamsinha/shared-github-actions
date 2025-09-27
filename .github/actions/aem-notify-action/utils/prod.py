"""create prod report"""
import os
import pytz
from datetime import datetime
import json
import yaml
from kpghalogger import KpghaLogger
logger = KpghaLogger()

action_path = os.getenv('GITHUB_ACTION_PATH')
workspace = os.getenv('GITHUB_WORKSPACE')
operation = os.getenv('OPERATION')
manifest = os.getenv('AEM_MANIFEST_NAME')
stage = os.getenv('MANIFEST_STAGE')
start_time = os.getenv('START_TIME')
end_time = os.getenv('END_TIME')


def update_report():
    if os.path.exists(f'{action_path}/report-deployment-results-kpo/kpo_deployment_results.yml'):
        with open(f'{action_path}/report-deployment-results-kpo/kpo_deployment_results.yml', '+r') as f:
            report_map = yaml.safe_load(f)
        f.close()
    else:
        report_map = {}
    stage_map = {}
    stage_map['start'] = start_time
    stage_map['end'] = end_time
    report_map[stage] = stage_map
    set_output(report_map)


def prod_notifications():
    with open(f'{workspace}/aem-manifests/{manifest.strip()}.json', '+r') as f:
        manifest_products = yaml.safe_load(f).get('products')
    f.close()
    with open(f'{action_path}/report-deployment-results-kpo/kpo_deployment_results.yml', '+r') as f:
        report_map = yaml.safe_load(f)
    f.close()
    html_message = """<html>
    <style>
    th { background-color: #ccc8c85c }
    .stage { background-color: #c0d8c0; }
    table { border-collapse: collapse; }
    table, td, th { border: 1px solid black; text-align: center; padding-left: 10px; padding-right: 20px; }
    </style>
    <body>
    """
    now = pytz.timezone('US/Pacific').localize(datetime.now()).strftime("%Y-%m-%d %H:%M")
    manifest_build = {}
    manifest_build['manifest'] = manifest
    manifest_build['started_by'] = os.getenv('GITHUB_ACTOR')
    manifest_build['build'] = f"""<a href="{os.getenv('BUILD_URL')}">Github Actions</a> {now}"""
    manifest_build['change_request'] = os.getenv('DEPLOY_TICKET')
    for k,v in manifest_build.items():
        html_message += f"<h4>{k.upper().replace('_',' ')}: {v}</h4>"
    html_message += '</table><table><tr><th>Manifest Artifacts</th></tr>'
    for x in manifest_products:
        html_message += f"<tr><td>{x.get('version')}</td></tr>"
    html_message += '</table><br><table><tr><th>Stage</th><th>Duration</th></tr>'
    for k,v in report_map.items():
        stage = k.upper().replace('-',' ')
        if stage == 'DEPLOY_ON_AEM':
            stage = 'DEPLOY_ON_AUTHOR_PREVIEW'
        duration = datetime.strptime(v.get('end'), '%m/%d/%Y:%H:%M:%S') - datetime.strptime(v.get('start'), '%m/%d/%Y:%H:%M:%S')
        html_message += f"<tr><td class='stage'>{stage}</td><td>{duration}</td></tr>"
    logger.info(yaml.safe_dump(report_map, sort_keys=False))
    set_output(html_message.replace('\n',''), 'html')
    set_post_deploy_map(manifest_products)
    set_notifications(html_message, manifest_products, ['kpo'])


def set_output(report_map, extension='yml'):
    path = f'{action_path}/kpo_deployment_results.{extension}'
    with open(path, '+w') as f:
        if extension == 'yml':
            f.write(yaml.safe_dump(report_map, sort_keys=False))
        else:
            f.write(report_map)
    f.close()
    os.system(f"echo 'report-content={report_map}' >> $GITHUB_OUTPUT")


def set_notifications(html_message, deploy_packages, deploy_envs):
    with open(f"{os.getenv('CONSTANTS_PATH')}/manifest_notifications.yml", 'r', encoding='utf-8') as f:
        manifest_notifications = yaml.safe_load(f)
    f.close()
    notification_map = {}
    if manifest.lower().startswith('non-prod'):
        email_recipients = manifest_notifications.get('nonprod-deploy-emails')
    elif manifest.lower().startswith('kp.org'):
        email_recipients = manifest_notifications.get('default-approval-emails')
    else:
        email_recipients = manifest_notifications.get('test-emails')
    for package in deploy_packages:
        if jira_reporter := package.get('jira', {}).get('jira_reporter'):
            email_recipients.append(jira_reporter)
    notification_map['email_recipients'] = list(set(email_recipients))
    notification_map['message'] = html_message.replace('\n','')
    notification_map['environment_notifications'] = True
    notification_map['environment'] = deploy_envs[0] # todo allow multiple environments
    email_subject = f'Manifest Deployment Results for {deploy_envs[0]}'
    if operation == 'post-deploy':
        email_subject += ' Completed'    
    notification_map['subject'] = email_subject
    os.system(f"echo 'notification-map={json.dumps(notification_map)}' >> $GITHUB_OUTPUT")


def set_post_deploy_map(manifest_products):
    post_deploy_map = {}
    post_deploy_products = []
    for x in manifest_products:
        post_deploy_products.append({
            'jira':x.get('jiraTicketId'),
            'name':x.get('version'),
            'product': {
                'name':x.get('name'),
                'version':x.get('version').split('-')[-1],
                'rollback': False,
                'app_type':'aem',
                'deploy_env':'kpo',
                'purge':False,
                'cd_deploy': x.get('cd_deploy')
            }
        })
    post_deploy_map['products'] = post_deploy_products
    post_deploy_map['jobs'] = len(post_deploy_products)
    logger.info(f'Post deploy map: {json.dumps(post_deploy_map, indent=2)}')
    os.system(f"echo 'result-map={json.dumps(post_deploy_map)}' >> $GITHUB_OUTPUT")
