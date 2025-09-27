import os
import yaml
import json
import re
import subprocess
import pytz
from datetime import datetime
import utils.prod as prod
from kpghalogger import KpghaLogger
logger = KpghaLogger()

workspace = os.getenv('GITHUB_WORKSPACE')
operation = os.getenv('OPERATION')
action_path = os.getenv('GITHUB_ACTION_PATH')
tabel_closing_tag = '</tbody></table>'


def main():
    try:
        # prod reports
        if operation == 'update-report':
            prod.update_report()
        elif operation == 'prod-notifications':
            prod.prod_notifications()
        # nonprod reports
        else:
            deploy_packages = yaml.safe_load(os.getenv('DEPLOY_PACKAGES'))
            deploy_env = yaml.safe_load(os.getenv('DEPLOY_ENVIRONMENT'))
            if type(deploy_env) is dict:
                deploy_envs = deploy_env.get('envs')
            elif deploy_env:
                deploy_envs = deploy_env.split(',')
            package_map = unarchive_package(deploy_packages, deploy_envs)
            if operation == 'check-environment':
                check_environment(package_map, deploy_packages)
            else:
                html_message = create_message(package_map, deploy_envs)
                prod.set_notifications(html_message, deploy_packages, deploy_envs)
    except RuntimeError as e:
        logger.error(f'Error creating manifest report: {e}')


def unarchive_package(deploy_packages, deploy_envs):
    package_deploy_map = {}
    for env in deploy_envs:
        for artifact in deploy_packages:
            artifact_name = artifact['name']
            rollback_info = artifact['module_values_rollback']['artifact_version']
            try:
                with open(f'{action_path}/deploy-results-{artifact_name}-{env}/package_deploy_map.json', 'r', encoding='utf-8') as a:
                    deployed_package = json.load(a)
                    deployed_package['rollback_version'] = rollback_info
                    package_deploy_map[artifact_name] = deployed_package
                    package_deploy_map[artifact_name]['package'] = artifact
                a.close()
            except FileNotFoundError as e:
                logger.error(f'Error fetching deploy data: {e}')
    return package_deploy_map


def create_message(package_deploy_map, deploy_envs):
    deploy_env = deploy_envs[0]
    # css
    html_message = """<html>
    <style>
    thead { background-color: #ccc8c85c }
    .OK, .SUCCESS, .PASS, .EXEMPT, .TRUE { background-color: #c0d8c0; }
    .ERROR, .FAILURE, .FAIL, .FALSE, .ROLLBACK { background-color: #ecbab4; }
    .SKIPPED, SKIPPED_ROLLBACK { background-color: #efefb5; }
    .UNSTABLE { background-color: #8ec2de }
    table { border-collapse: collapse; width: 80% }
    table, td, th { border: 1px solid black; text-align: center; }
    </style>
    <body>
    """
    
    # report per environment
    now = pytz.timezone('US/Pacific').localize(datetime.now()).strftime("%Y-%m-%d %H:%M")
    html_message += f"""
    <h3>Deploy Environment: {deploy_env}</h3>
    <h4>Manifest Name: {os.getenv('AEM_MANIFEST_NAME')}</h4>
    <h4><a href=\"{os.getenv('BUILD_URL')}\">Github Build</a> {now} PST</h4>
    """

    if re.match('run-tests', os.getenv('DEPLOY_OPERATION')):
        html_message += html_report_tests(package_deploy_map)
    else:
        html_message += html_report_deploy(package_deploy_map)

    # set output for github pages
    html_report = html_message.replace('\n','')
    os.system(f"echo 'report-content={html_report}' >> $GITHUB_OUTPUT")
    with open(f'{action_path}/{deploy_env}_deployment_results.html', 'w+', encoding='utf-8') as f:
        f.write(html_message)
    f.close()
    return html_message


def html_report_tests(package_deploy_map):
        html_message = f'<h4>Test Results</h4>'
        html_message += f"""
        <table cellpadding=\"5\"><thead><tr>
        <th style=\"white-space: nowrap;\">Package</th>
        <th style=\"white-space: nowrap;\">Smoke Result</th>
        <th>Result</th></tr></thead><tbody>
        """
        for result_map in package_deploy_map.values():
            artifact_info = result_map['package']['module_values_deploy']
            post_deploy = result_map.get('post_deploy')
            if not post_deploy: continue
            test_result = post_deploy.get('test_result','N/A').upper()
            css_quality_class = test_result
            html_message += f"""
            <tr class=\"{css_quality_class}\">
            <td>{artifact_info.get('artifact_id')}-{artifact_info.get('artifact_version')}</td>
            <td><a href=\"{post_deploy.get('test_url')}\">{test_result}</a></td>
            <td>{post_deploy.get('comments')}</td></tr>
            """
        html_message += tabel_closing_tag
        html_message += '</body></html>'
        return html_message

    
def html_report_deploy(package_deploy_map):
    overall_build_success = True
    # quality
    html_message = '<h4>Quality</h4>'
    html_message += """
    <table cellpadding=\"5\"><thead><tr>
    <th style=\"white-space: nowrap;\">Package</th>
    <th style=\"white-space: nowrap;\">Rollback Package</th>
    <th style=\"white-space: nowrap;\">Jira</th>
    <th style=\"white-space: nowrap;\">AMS CQ Gate</th>
    <th style=\"white-space: nowrap;\">SonarQube Quality Gate</th>
    <th style=\"white-space: nowrap;\">SQ Remediation</th>
    <th style=\"white-space: nowrap;\">Regression Quality Gate</th>
    <th style=\"white-space: nowrap;\">Regression Pass %</th>
    <th style=\"white-space: nowrap;\">Regression Remediation</th></tr></thead><tbody>
    """
    for result_map in package_deploy_map.values():
        package = result_map.get('package')
        artifact_info = package['module_values_deploy']
        jira_info = package['jira']
        rollback_package = package['module_values_rollback']
        rollback_details = '-'.join([v for k, v in rollback_package.items() if k != 'secondary_ids' and v != 'N/A']) or 'N/A'
        quality_info = result_map.get('quality')
        sonar_quality = quality_info.get('sonar').upper()
        regression_quality = quality_info.get('regression').upper()
        css_quality_class = sonar_quality if sonar_quality != 'ok' else regression_quality
        jira_url = f"{os.getenv('JIRA_URL')}/browse/{jira_info.get('jira_id')}" if jira_info else 'N/A'
        html_message += f"""
        <tr class=\"{css_quality_class}\">
        <td>{artifact_info.get('artifact_id')}-{artifact_info.get('artifact_version')}</td>
        <td>{rollback_details}</td>
        <td><a href=\"{jira_url}\">{jira_url.split('/')[-1]}</a></td>
        <td>{quality_info.get('ams').upper()}</td>
        <td>{sonar_quality}</td>
        <td>{quality_info.get('sonar_date')}</td>
        <td>{regression_quality}</td>
        <td>{quality_info.get('regression_pass')}</td>
        <td>{quality_info.get('regression_date')}</td></tr>"""
    html_message += tabel_closing_tag

    # deploy
    if operation == 'post-deploy':
        # critical tests
        if os.getenv('CRITICAL_RESULT'):
            html_message += '<h4>Critical Tests</h4>'
            html_message += """
            <table cellpadding=\"5\"><thead><tr>
            <th style=\"white-space: nowrap;\">Package</th>
            <th style=\"white-space: nowrap;\">Pre-deploy Result</th>
            <th style=\"white-space: nowrap;\">Post-deploy Result</th>
            <th style=\"white-space: nowrap;\">Critical Pass</th></tr></thead><tbody>
            """
            for result_map in package_deploy_map.values():
                artifact_info = result_map['package']['module_values_deploy']
                post_deploy = result_map.get('post_deploy')
                quality_map = result_map.get('quality')
                if not post_deploy:
                    continue
                critical_post = post_deploy.get('critical_post','SKIPPED')
                critical_pass = 'FALSE' if post_deploy.get('critical_fail',False) else 'TRUE'
                css_quality_class = critical_pass
                html_message += f"""
                <tr class=\"{css_quality_class}\">
                <td>{artifact_info.get('artifact_id')}-{artifact_info.get('artifact_version')}</td>
                <td>{quality_map.get('critical_pre','SKIPPED')}</a></td>
                <td>{critical_post}</td>
                <td>{critical_pass}</td></tr>
                """
            html_message += tabel_closing_tag
        
        html_message += f'<h4>Deployment</h4>'
        html_message += f"""
        <table cellpadding=\"5\"><thead><tr>
        <th style=\"white-space: nowrap;\">Package</th>
        <th style=\"white-space: nowrap;\">Rollback Version</th>
        <th style=\"white-space: nowrap;\">Smoke Result</th>
        <th style=\"white-space: nowrap;\">Deployment Result</th>
        <th style=\"white-space: nowrap;\">Remediation Date</th>
        <th>Result</th></tr></thead><tbody>
        """
        for result_map in package_deploy_map.values():
            artifact_info = result_map['package']['module_values_deploy']
            rollback_package = result_map['package']['module_values_rollback']
            rollback_details = '-'.join([v for k, v in rollback_package.items() if k != 'secondary_ids' and v != 'N/A']) or 'N/A'
            post_deploy = result_map.get('post_deploy')
            if not post_deploy: continue
            build_result = post_deploy.get('overall_status').upper()
            if build_result != 'success':
                overall_build_success = False
            test_result = post_deploy.get('test_result','N/A').upper()
            css_quality_class = build_result
            html_message += f"""
            <tr class=\"{css_quality_class}\">
            <td>{artifact_info.get('artifact_id')}-{artifact_info.get('artifact_version')}</td>
            <td>{rollback_details}</td>
            <td>{test_result}</td>
            <td>{build_result}</td>
            <td>{result_map.get('quality').get('autorollback_date')}</td>
            <td>{post_deploy.get('comments')}</td></tr>
            """
        html_message += tabel_closing_tag
        html_message += '</body></html>'
    os.system(f"echo 'result-map={overall_build_success}' >> $GITHUB_OUTPUT")
    return html_message


def check_environment(package_map, deploy_packages):
    """remove packages which do not pass quality check from deploy packages"""
    exclude_package_map = {}
    exclude_package_map['packages'] = []
    remove_packages = []
    comment_map = {}
    pass_checks = True
    comment = ''

    for package in package_map.values():
        quality_fail = package.get('quality').get('quality_fail')
        artifact_id = package.get('name')
        if quality_fail:
            artifact_id = package.get('name')
            logger.error(f'Artifact {artifact_id} did not meet quality standards. Removing from deploy packages.')
            msg = f'Quality checks failed for {artifact_id}'
            subprocess.run([f"""echo "#### :x: {msg}" >> $GITHUB_STEP_SUMMARY"""], shell=True, check=True)
            remove_packages.append(artifact_id)
            pass_checks = False
            comment += f':x: Quality check failed for {artifact_id}\n'
        else:
            comment += f':white_check_mark: Quality check passed for {artifact_id}\n'
    for remove_package in remove_packages:
        for deploy_package in deploy_packages:
            if deploy_package.get('name') == remove_package:
                exclude_package_map['packages'].append({"package":deploy_package})
    logger.info(f'Packages to exclude:\n{yaml.safe_dump(exclude_package_map, indent=2)}')
    if os.getenv('GITHUB_EVENT_NAME') == 'pull_request':
        comment_map['result'] = pass_checks
        comment_map['comment'] = comment
        os.system(f"echo 'result-map={json.dumps(comment_map)}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'exclude-packages={json.dumps(exclude_package_map)}' >> $GITHUB_OUTPUT")


if __name__ == '__main__':
    main()
