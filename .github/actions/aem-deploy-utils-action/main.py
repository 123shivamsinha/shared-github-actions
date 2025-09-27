import os
import yaml
import json
import re
import logging
import requests
from datetime import datetime, timezone
import pytz
import utils.cache as cache
from utils import vault

deploy_env = os.getenv('DEPLOY_ENV')
log_level = os.getenv('LOG_LEVEL') if os.getenv('LOG_LEVEL') else '20'
logging.basicConfig(level=int(log_level), format='%(asctime)s :: %(levelname)s :: %(message)s')
COLOR_RED = "\u001b[31m"
COLOR_GREEN = "\u001b[32m"


def main():
    """main function"""
    operation = os.getenv('OPERATION')
    aem_manifest = os.getenv('MANIFEST_DEPLOY') or ''
    deploy_ticket = os.getenv('DEPLOY_TICKET')
    deployment_data = yaml.safe_load(os.getenv('DEPLOYMENT_DATA') or '{}')
    deploy_map = yaml.safe_load(os.getenv('DEPLOY_PACKAGE') or '{}')
    context = yaml.safe_load(os.getenv('CONTEXT') or '{}')
    manifest_deploy = True if aem_manifest else False
    if re.match('vault-details|generate-csv', str(operation)):
        vault.get_vault_details(deploy_env)
    elif operation == 'aem-cache-flush':
        cache.cache_flush(deploy_env)
    elif operation == 'jira-data':
        set_jira_ticket_details(deployment_data, deploy_map, manifest_deploy, context)
    elif operation == 'validate-ticket':
        validate_ticket(deploy_ticket)
    elif operation == 'security-test':
        cache.security_test()
    elif operation == 'cd-manifest-deploy':
        cd_manifest_deploy(aem_manifest)
    elif operation == 'update-automation-constants':
        update_automation_constants()


def set_jira_ticket_details(deployment_data, deploy_map, manifest_deploy, context):
    """set jira ticket output"""
    auto_deploy = deploy_map.get('cd_deploy')
    operation = deployment_data.get('operation', '')
    snapshot_version = 'snapshot' in deploy_map['module_values_deploy']['artifact_version']
    jira_ticket_details = {}
    sre_id = ''
    post_deploy = deployment_data.get('post_deploy', {})
    overall_status = post_deploy.get('overall_status', 'N/A')
    test_result = post_deploy.get('test_result', 'N/A')
    p1_total_tests = post_deploy.get('p1_total_tests', 'N/A')
    target_total_tests = post_deploy.get('target_total_tests', 'N/A')
    p1_result = post_deploy.get('p1_status', 'N/A')
    target_result = post_deploy.get('target_status', 'N/A')
    regression_result = post_deploy.get('regression_result', 'N/A')
    if auto_deploy and not snapshot_version: # repo autodeploy flow
        jira_ticket_details = auto_ticket_details(deployment_data, deploy_map, manifest_deploy, context)
        sre_id = deployment_data.get('auto_deploy').get('sre_id')
    elif manifest_deploy and not auto_deploy: # standard manifest flow
        jira_ticket_details['jiraTicketId'] = deploy_map['jira']['jira_id']
        jira_ticket_message = post_deploy.get('comments', '')
        valid_test_results = ['pass', 'SUCCESS', 'SKIPPED']
        emojis = {key: "(/)" if value in valid_test_results else "(x)" for key, value in {"test_result": test_result, "p1_result": p1_result, "target_result": target_result}.items()}
        test_result_emoji, p1_emoji, target_emoji = emojis["test_result"], emojis["p1_result"], emojis["target_result"]
        if deploy_env == 'kpoi1' or deploy_env == 'kpod2':
            overall_test_result = f"\n {test_result_emoji} *Smoke test:* *Env:*  {deploy_env}; *Test Status:* {test_result}"
        else:
            overall_test_result = f"\n {test_result_emoji} *Smoke test:* *Env:*  {deploy_env}; *Test Status:* {test_result};  \n {p1_emoji} *P1 test status:* *Env:*  {deploy_env}; *P1 Status:*  {p1_result}; *Total P1 Tests:*  {p1_total_tests} \n {target_emoji} *Target test status:* *Env:*  {deploy_env}; *Target Status:*  {target_result}; *Total Target Tests:*  {target_total_tests} \n" 
        jira_ticket_details['message'] = f'{jira_ticket_message}.  {overall_test_result}'
        if overall_status == 'success' and deployment_data.get('operation') != 'promote-to-stage':
            jira_ticket_status = '91'
            jira_action = 'comment_transition'
        else:
            jira_ticket_status = ''
            jira_action = 'comment'
        jira_ticket_details['action'] = jira_action
        jira_ticket_details['operation'] = 'manifest-utils'
        jira_ticket_details['transitionId'] = jira_ticket_status
        jira_ticket_details['deploy_action'] = 'jira-comments'
        jira_ticket_details['process_ticket'] = True
    else:
        logging.info(f'Not autodeploy or quality checks failed. Not preceeding to further environments.')
    if jira_ticket_details:
        logging.info('%sJira ticket data:\n%s', COLOR_GREEN, json.dumps(jira_ticket_details, indent=2))
        os.system(f"echo 'jira-ticket-details={json.dumps(jira_ticket_details)}' >> $GITHUB_OUTPUT")
    if manifest_deploy:
        set_test_output(deploy_map, test_result, regression_result, manifest_deploy, sre_id, operation, auto_deploy)     
    else:
        logging.info('Not creating or updating Jira ticket.')


def auto_ticket_details(deployment_data, deploy_map, manifest_deploy, cd_quality):
    jira_ticket_details = {}
    cd_threshold_pass = cd_quality.get('continue_deploy')
    cd_quality_summary = cd_quality.get('summary')
    auto_deploy = deployment_data.get('auto_deploy')
    cd_quality = deployment_data.get('quality', {})
    appsec_fail = cd_quality.get('appsec_fail', False)
    jira_subtask_updates = cd_quality.get('jira_subtask_updates', {})
    if ams_content_deploy := auto_deploy.get('content', False):
        content_message = f"\n(+) Added or updated AMS content to deployment: {ams_content_deploy.get('content_id')}:{ams_content_deploy.get('content_version', '')}."
    next_env_name = auto_deploy['next_env_name']
    post_deploy = deployment_data.get('post_deploy',{}).get('overall_status')
    operation = deployment_data.get('operation', 'N/A')
    release_date = auto_deploy.get('snow_details', {}).get('ScheduledDate', '')
    overall_success = True if not appsec_fail and (not post_deploy or (re.match('success|skipped_rollback', post_deploy) and cd_threshold_pass)) else False
    jira_ticket_details['deploy_action'] = 'update-deploy-ticket'
    jira_ticket_details['jiraTicketId'] = deploy_map['jira']['jira_id'] if manifest_deploy else auto_deploy.get('jira_id')
    if manifest_deploy:
        jira_ticket_details, process_deploy_ticket, transition_id = manifest_auto_ticket_details(jira_ticket_details, release_date, auto_deploy, overall_success, next_env_name, operation)
    else:
        jira_ticket_details, process_deploy_ticket, transition_id = repo_auto_ticket_details(jira_ticket_details, auto_deploy, overall_success, next_env_name)
    jira_ticket_details['operation'] = 'manifest-utils'
    jira_ticket_details['transitionId'] = transition_id or ''
    jira_ticket_details['action'] = 'comment_transition' if transition_id else 'comment'
    jira_ticket_details['process_ticket'] = process_deploy_ticket
    jira_ticket_details['message'] += cd_quality_summary
    if ams_content_deploy:
        jira_ticket_details['message'] += content_message
    jira_ticket_details['jira_subtasks'] = jira_subtask_updates
    if re.match('PREPROD|STAGE|PROD', next_env_name) and overall_success and deployment_data.get('name') != 'ams-configs':        
        jira_ticket_details['deploy_action'] = 'jira-comments-preprod'
    return jira_ticket_details


def manifest_auto_ticket_details(jira_ticket_details, release_date, auto_deploy, overall_success, next_env_name, operation):
    process_deploy_ticket = False if operation.startswith('run-tests') else True
    transition_id = None
    env_name, next_env, env_id = auto_deploy['env_name'], auto_deploy['next_env'], auto_deploy['env_id']
    ticket_env = deploy_env.upper()
    jira_ticket_details['method'] = 'POST'
    if not overall_success:
        message = f'(x) Unsuccessful deployment to *{ticket_env}*. '
        next_env = ticket_env # remain at current env
        transition_id = '251' # cancel ticket
        jira_ticket_details['method'] = 'DELETE'
    else:
        message = f'(/) Successfully deployed to *{ticket_env}*. '
        transition_id = env_id
        if next_env:
            message += f'Continuing automated deployment to *{next_env.upper()}*.'
            message += get_next_env_message(next_env_name, release_date)
            if re.match('STAGE|PROD', next_env_name):
                process_deploy_ticket = False
        else:
            message += f'*Deployed to all lower environments configured in RRC, ending with {env_name}*. Closing ticket as preprod was not enabled. To continue deployments, either enable additional non-prod environments in RRC, or enable PREPROD.'
            process_deploy_ticket = False
    jira_ticket_details['env'] = next_env or ''
    jira_ticket_details['message'] = message + '\n'
    return jira_ticket_details, process_deploy_ticket, transition_id


def repo_auto_ticket_details(jira_ticket_details, auto_deploy, overall_success, next_env_name): # TODO combine with manifest
    process_deploy_ticket = True if overall_success else False
    transition_id = None
    next_env, env_id, last_lower_env = auto_deploy['next_env'], auto_deploy['env_id'], auto_deploy['last_lower_env']
    message = ''
    if last_lower_env and next_env and process_deploy_ticket:
        transition_id = env_id
        jira_key = auto_deploy.get('jira_id')
        if jira_key:
            jira_ticket_url = f"{os.getenv('JIRA_URL')}/browse/{jira_key}"
            os.system(f'echo "#### :clipboard: [Jira deploy ticket]({jira_ticket_url})" >> $GITHUB_STEP_SUMMARY')
            if auto_deploy.get('update_release'):
                message += f'(i) Release date or version has been modified. Updating ticket with new fields. '
            message += f'(i) Updating ticket for next deployment to *{next_env.upper()}*. '
        else:
            jira_ticket_details['deploy_action'] = 'create-deploy-ticket'
        message += get_next_env_message(next_env_name)
        jira_ticket_details['env'] = next_env
        logging.info('Last lower environment - no further deployments from repo. Creating deployment ticket.')
        jira_ticket_details['method'] = 'POST'
    elif not process_deploy_ticket:
        logging.info('Continuous Deployment failed - not creating deploy ticket.')
    else:
        logging.info('Last lower environment - no further deployments configured in RRC.')
        process_deploy_ticket = False
    jira_ticket_details['message'] = message
    return jira_ticket_details, process_deploy_ticket, transition_id


def get_next_env_message(next_env_name, release_date='release date'):
    automation_schedule = yaml.safe_load(os.getenv('AEM_CD_SCHEDULE','{}'))
    utc_now = datetime.now(timezone.utc)
    pst_now = utc_now.astimezone(pytz.timezone('US/Pacific'))
    pst_hour = pst_now.hour
    hours = automation_schedule.get(next_env_name.lower(), [])
    if not hours:
        return ''
    hours = [int(h) for h in hours]
    # filter out past hours
    future_hours = [h for h in hours if h > pst_hour]
    message = 'today'
    # if there are no further deployments today, wrap around to the next day
    if not future_hours:
        future_hours = hours
        message = 'next business day'
    # find the next deployment
    next_hour = min(future_hours)
    if re.match('PREPROD', next_env_name):
        next_env_message = f" Preprod deployment will be the *weekday* before release date *{release_date}* at *{next_hour}:00 PST*.\n "
    elif re.match('STAGE', next_env_name):
        next_env_message = f" Next stage deployment will be *{release_date}* at *{next_hour}:00 PST*.\n "
    elif next_env_name != 'PROD':
        next_env_message = f" Next manifest deploy will be {message} at *{('0' if next_hour < 10 else '')}{next_hour}:00 PST*.\n "
    return next_env_message


def validate_ticket(deploy_ticket):
    if not deploy_ticket or len(deploy_ticket) < 4 or not re.match('rm-', deploy_ticket[0:3].strip().casefold()):
        raise Exception("Please provide valid Jira RM Ticket number in the format RM-XXXXXX")


def set_test_output(deploy_map, test_result, regression_result, manifest_deploy, sre_id, operation, auto_deploy):
    """set output for creating jira failure issues"""
    if re.match('FAILURE|fail', test_result) or re.match('FAILURE|fail', regression_result):
        if auto_deploy and operation == '':
            logging.info('Auto deploy lower environment failure: not creating failure issue.')
            return
        deploy_map['manifest'] = manifest_deploy
        deploy_map['smoke'] = test_result
        deploy_map['regression'] = regression_result
        deploy_map['env'] = deploy_env
        deploy_map['sre_id'] = sre_id
        os.system(f"echo 'jira-failure-details={json.dumps(deploy_map)}' >> $GITHUB_OUTPUT")


def cd_manifest_deploy(aem_manifest):
    try:
        workflow_repo = os.getenv('GITHUB_REPOSITORY')
        rm_ticket = os.getenv('RM_TICKET') or 'RM-123456'
        workflow_name = 'prod.yml'
        payload = {
            "ref": "master",
            "inputs": {"aem-manifest": aem_manifest, "service-now": rm_ticket}
        }
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.getenv('APP_TOKEN')}",
            "Content-Type": "application/json"
        }
        url = f"{os.getenv('GITHUB_SERVER_URL')}/api/v3/repos/{workflow_repo}/actions/workflows/{workflow_name}/dispatches"
        response = requests.request("POST", url, json=payload, headers=headers)
        if response.status_code == 204:
            logging.info(f"Triggered workflow {workflow_name} for {aem_manifest} with inputs: {json.dumps(payload['inputs'])}")
        else:
            logging.error(f"Failed to trigger workflow {workflow_name} for {aem_manifest}: {response.text}")
    except requests.exceptions.RequestException as e:
        logging.error(e)


def update_automation_constants():
    """update automation constants"""
    try:
        constant_update = {}
        disabled_envs = []
        path = os.getenv('GITHUB_WORKSPACE')
        with open(os.path.join(path, 'automation.yml'), 'r') as file:
            automation_config = yaml.safe_load(file)
        for key, value in automation_config.items():
            if key in {'id', 'enabled'}:
                continue
            constant = yaml.safe_load(os.getenv(f'AEM_CD_{key.upper()}', '{}'))
            if key == 'schedule':
                for k, v in value.items():
                    constant[k] = v['schedule']
                    if not v.get('enabled', True):
                        disabled_envs.append(k)
            elif key == 'environment_mapping':
                # Remove disabled envs in one pass
                for x in disabled_envs:
                    value.pop(x, None)
                    constant.pop(x, None)
                constant.update(value)
            else:
                constant = value
            constant_update[f'AEM_CD_{key.upper()}'] = json.dumps(constant)
        os.system(f'echo "cd-schedule={json.dumps(constant_update)}" >> $GITHUB_OUTPUT')
    except (KeyError, FileNotFoundError, Exception) as e:
        logging.error(f"Failed to update automation constants: {e}")


main()
