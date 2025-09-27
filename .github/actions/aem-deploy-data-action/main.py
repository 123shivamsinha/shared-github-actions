"""
This action creates a deployment data map used for mananging deployment data in the AEM deployment process.
- The main module provides the operation flow control and notifications functions.
- The utils/data module provides the data classes and class methods for creating the deployment data map in aem_deploy_pre workflow.
- The utils/utils module provides the utility functions for updating the deployment data map and other actions.
"""
import os
import json
import yaml
import re
import subprocess
import utils.utils as utils
from utils.data import DeploymentData
from kpghalogger import KpghaLogger
logger = KpghaLogger()


def main():
    """main method"""
    operation = os.getenv('OPERATION')
    deploy_package = yaml.safe_load(os.getenv('DEPLOY_PACKAGE', '{}'))
    deployment_data = get_deployment_data()
    match(operation):
        case 'create-deploy-map':                                                   # create deployment data {'quality', 'rollback', 'deploy_package'}
            deployment_data = create_deploy_map(deploy_package)
        case 'post-deploy':                                                         # update deployment data post-deploy {'deploy'}
            deployment_data = utils.post_deploy(deployment_data)
        case 'check-deploy-map':                                                    # check deployment data for post-deploy test cases
            deployment_data = utils.check_deploy_map(deployment_data)
        case 'post-deploy-test':                                                    # update deployment data post-deploy tests {'post_deploy'}
            deployment_data = utils.post_deploy_test(deployment_data)
        case 'deploy-data':                                                         # set deployment data for post deploy flow
            deployment_data = utils.set_deploy_data(deployment_data)
        case 'aem-notifications':                                                   # set notifications for AEM deployment
            deployment_data = set_notifications(deployment_data)
        case _:
            raise RuntimeError('Operation not found.')
    if deployment_data:
        output = deployment_data.to_json()
        logger.info(f'Deployment data:\n{json.dumps(output, indent=2)}')
        utils.set_output('deployment-data', json.dumps(output))
        utils.set_output('package-name', deployment_data.name) 
        deployment_data.to_file()


def get_deployment_data():
    """read downloaded deployment data maps from workspace"""
    try:
        workspace = os.getenv('GITHUB_WORKSPACE')
        if not os.path.exists(f'{workspace}/package_deploy_map.json'):
            return
        with open(f'{workspace}/package_deploy_map.json', 'r+', encoding='utf-8') as f:
            data = json.load(f)
        deployment_data = DeploymentData(**data)
        return deployment_data
    except FileNotFoundError as e:
        raise FileNotFoundError(f'Error fetching deploy data: {e}') from e

    
def create_deploy_map(deploy_package):
    """
    Deployment data map created during pre-deployment steps.
    This will set {'quality', 'rollback', 'deploy_package'} blocks for the deployment data map.
    """
    try:
        manifest_deploy = bool(os.getenv('MANIFEST_DEPLOY'))
        deployment_data = DeploymentData(
            env=os.getenv('DEPLOY_ENV').lower(),
            operation=os.getenv('DEPLOY_OPERATION', 'push event'),
            manifest_deploy=manifest_deploy,
            deploy_package=deploy_package
        ).create_map().add_rollback() # create deployment data map and add rollback
        utils.set_output('rollback-enabled', deployment_data.quality.autorollback_enabled)
        if deployment_data.auto_deploy:
            utils.set_output('deploy-data', json.dumps(deployment_data.auto_deploy.to_json()))
        return deployment_data
    except RuntimeError as e:
        raise RuntimeError(f'Error creating deploy map: {e}') from e


def set_notifications(deployment_data):
    post_deploy = deployment_data.post_deploy
    deploy_package = deployment_data.deploy_package
    manifest_deploy = os.getenv('MANIFEST_DEPLOY')
    deploy_env = deployment_data.env
    auto_deploy = deploy_package.get('cd_deploy')
    jira_ticket = os.getenv('ARTIFACTORY_PROP')
    if post_deploy:
        if auto_deploy:
            deployment_data = set_notifications_cd(deployment_data, deploy_package, deploy_env, manifest_deploy, jira_ticket)
        else:
            set_notifications_standard(deployment_data, deploy_package, deploy_env, manifest_deploy)
        set_insights_data(deployment_data, deploy_package, manifest_deploy)
    if jira_ticket and auto_deploy:
        jira_update = deployment_data.quality.get('jira_subtask_updates')  # update subtasks in JIRA deployment ticket
        if jira_update:
            utils.set_output('jira-comment', json.dumps(jira_update))
    return deployment_data
       

def set_insights_data(deployment_data, deploy_map, manifest_deploy=False):
    rollback = deployment_data.post_deploy.get('overall_status') == 'rollback'
    deploy_data = deploy_map['module_values_deploy']
    deploy_data['rollback_version'] = deployment_data.deploy_package.get('module_values_rollback', {}).get('artifact_version')
    deploy_data['rollback'] = rollback
    deploy_data['app_type'] = 'aem'
    deploy_data['deploy_env'] = deployment_data.env
    deploy_data['name'] = deployment_data.name
    deploy_data['manifest'] = manifest_deploy
    deploy_data['build_url'] = os.getenv('BUILD_URL')
    logger.info(f'Deploy data for Insights:\n{json.dumps(deploy_data, indent=2)}')
    utils.set_output('deploy-data', json.dumps(deploy_data))


def set_notifications_standard(deployment_data, deploy_map, deploy_env, manifest_deploy):
    post_deploy = deployment_data.post_deploy
    test_url = post_deploy.get('test_url')
    msg = post_deploy.get('comments')
    test_result = post_deploy.get('test_result', 'N/A')
    p1_total_tests = post_deploy.get('p1_total_tests', 'N/A')
    target_total_tests = post_deploy.get('target_total_tests', 'N/A')
    p1_result = post_deploy.get('p1_status', 'N/A')
    target_result = post_deploy.get('target_status', 'N/A')
    overall_test_result = f"\n*Smoke* -> Status: {test_result}; \n*P1* -> Status: {p1_result}; Total Tests: {p1_total_tests}\n*Target* -> Status: {target_result}; Total Tests: {target_total_tests}\n"    
    msg = f"{msg}. {overall_test_result}"
    test_urls = ''
    if test_url:
        test_urls += f'[Smoke result]({test_url})'
    if re.match('Deployment successful|SUCCESS', msg):
        subprocess.run([f"""echo "#### :rocket: {msg} {test_urls}" >> $GITHUB_STEP_SUMMARY"""], shell=True)
    elif len(re.findall('Rolled back|CRITICAL TEST FAILURE', msg)) > 0:
        subprocess.run([f"""echo "#### :parachute: {msg} {test_urls}" >> $GITHUB_STEP_SUMMARY"""], shell=True)
    else:
        subprocess.run([f"""echo "#### :information_source: {msg} {test_urls}" >> $GITHUB_STEP_SUMMARY"""], shell=True)        
    set_notify_map(deployment_data, deploy_map, deploy_env, msg, manifest_deploy)


def set_notifications_cd(deployment_data, deploy_map, deploy_env, manifest_deploy, jira_ticket=None):
    jira_ticket_details, auto_deploy_details, test_details = '', '', ''
    cd_result = yaml.safe_load(os.getenv('CD_RESULT', '{}'))
    cd_msg = cd_result.get('summary', '')
    cd_status = os.getenv('TEST_RESULT')
    jira_url = os.getenv('JIRA_URL')
    post_deploy = deployment_data.post_deploy  
    auto_deploy = deployment_data.auto_deploy
    test_url = post_deploy.get('test_url')
    result = post_deploy.get('overall_status','success')
    overall_passed = True if re.match('success|skipped_rollback', result) and cd_status =='True' else False
    if not overall_passed:
        rollback_scenario = True
        deployment_data.deploy['rollback'] = rollback_scenario
    bg_color = "green"  if overall_passed else "red"
    overall_status = 'SUCCESS' if overall_passed else 'FAILURE'
    if jira_ticket:
        jira_ticket_details = f"<tr><td>Jira Deployment Ticket</td><td><a href='{jira_url}/browse/{jira_ticket}'>{jira_ticket}</a></td></tr>"
        auto_deploy_details = f"<tr><td>Next environment</td><td>{auto_deploy.get('next_env')} ({auto_deploy.get('next_env_name')})</td></tr>"
    if test_url:
        test_details = f"<tr><td>Test URL</td><td>{test_url}</td></tr>"
    notification_msg = f"""<html>
        <table border="1" cellpadding="5">
            <tr><td colspan=2 cellpadding=5 bgcolor="{bg_color}"><h4>Continuous deployment {overall_status} for {deploy_map['name']}</h4></td></tr>
            <tr><td>Result</td><td>{post_deploy.get('comments')}</td></tr>
            <tr><td>Deploy Result</td><td>{result}</td></tr>
            <tr><td>CD Quality Pass</td><td>{cd_status}</td></tr>
            {jira_ticket_details}
            {auto_deploy_details}
            {test_details}
            <tr><td colspan=2 bgcolor="{bg_color}"><h4>{cd_msg}</h4></td></tr>
        </table>
    </html>"""
    set_notify_map(deployment_data, deploy_map, deploy_env, notification_msg, manifest_deploy)
    return deployment_data


def set_notify_map(deployment_data, deploy_map, deploy_env, notification_msg, manifest_deploy):
    notify_map = None
    post_deploy = deployment_data.post_deploy
    artifact_name = deploy_map.get('module_values_deploy').get('artifact_id')
    notification_map = deploy_map.get('app_props',{}).get('notification_map', {})
    if notification_map or manifest_deploy:
        notify_email = notification_map.get('email_recipients') or []
        if manifest_deploy:
            notify_email.append(deploy_map.get('jira').get('jira_reporter'))
        else:
            notify_email.append(f"{os.getenv('GITHUB_ACTOR')}@kp.org")
        auto_deploy = getattr(deployment_data, 'auto_deploy', None) or {}
        notify_teams = notification_map.get('teams_channel') or auto_deploy.get('teams_channel')
        overall_status = post_deploy.get('overall_status')
        notify_map = {
            'build_status': overall_status,
            'message': notification_msg, 
            'environment': deploy_env, 
            'artifact_name': artifact_name, 
            'email_recipients': notify_email,
            'teams_channel': notify_teams
        }
        logger.debug(f'Notification map:\n{yaml.safe_dump(notify_map, indent=2)}')
        utils.set_output('notification-map', json.dumps(notify_map))
    else:
        logger.info('No notifications configured.')


if __name__ == "__main__":
    main()
