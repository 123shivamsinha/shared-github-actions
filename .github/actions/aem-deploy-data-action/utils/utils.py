"""create deployment data map used for reporting"""
import os
import re
import json
import yaml
import traceback
from kpghalogger import KpghaLogger
logger = KpghaLogger()


def post_deploy(deployment_data):
    """
    Post-deploy update of deployment data map - evaluate rollback scenario based on deployment and critical test results.
    This will set the 'deploy' block of the deployment data map.
    """
    try:
        deploy_package = deployment_data.deploy_package
        rollback_enabled = deployment_data.quality.get('autorollback_enabled')
        rollback_artifact = deploy_package.get('module_values_rollback')
        deploy_result = deployment_data.deploy.get('deploy_status', 'N/A')
        post_deploy = deployment_data.post_deploy
        deploy_skipped = 'SKIPPED' in deploy_result

        critical_fail = False
        critical_results_pre = deployment_data.quality.get('critical_pre')
        critical_results_post = yaml.safe_load(os.getenv('CRITICAL_POST', '{}'))
        if critical_results_pre and critical_results_post:
            critical_post = critical_results_post.get('jobs_passed')
            post_deploy['critical_post'] = critical_post
            if int(critical_results_pre) > int(critical_post) + 5:
                critical_fail = True
        post_deploy['critical_fail'] = critical_fail

        rollback_scenario = False
        if re.match('run-tests|promote-to-stage', deployment_data.operation):
            comment = f"Rollback not enabled for {deployment_data.operation}."
        elif any([deploy_result == 'FAILED', critical_fail]) and all([rollback_enabled, rollback_artifact]):
            rollback_scenario = True
            rollback_version = deploy_package.get('module_values_rollback', {}).get('artifact_version')
            if critical_fail:
                comment = f"Critical test failure for {deployment_data.name}. Rolled back to version {rollback_version}. "
            elif deploy_result == 'FAILED':
                comment = f"Deploy failed for {deployment_data.name}. Rolled back to version {rollback_version}. "
        elif deploy_skipped:
            comment = f"Deployment skipped for {deployment_data.name}. Version already deployed in {deployment_data.env}."
        else:
            comment = f"Deployment successful for {deployment_data.name} in {deployment_data.env}."
        post_deploy['comments'] = comment

        deployment_data.deploy['rollback'] = rollback_scenario
        deployment_data.post_deploy = post_deploy
        logger.info(f'Post-deploy rollback scenario: {rollback_scenario}')
        set_output('rollback-scenario', rollback_scenario)
        return deployment_data
    except (KeyError, AttributeError, Exception) as e:
        logger.error(f"Error in post_deploy: {e} - {traceback.format_exc()}")
        return False


def check_deploy_map(deployment_data):
    """determine post-deploy testing scenarios by checking deployment data map"""
    try:
        aem_deploy_env = os.getenv('AEM_ENV_MAP')
        env_sync_job = os.getenv('GITHUB_REPOSITORY') == 'CDO-KP-ORG/ams-manifest-sync'
        test_package_list = yaml.safe_load(os.getenv('TEST_PACKAGES', '[]'))
        smoke_tests = os.getenv('SMOKE_TEST') == 'true'

        run_tests = {}
        rollback_enabled = deployment_data.quality.get('autorollback_enabled')
        package_name = deployment_data.name
        test_included = package_name in test_package_list
        deploy_env = deployment_data.env
        deploy_map = deployment_data.deploy
        auto_deploy_map = deployment_data.auto_deploy
        deploy_fail = deploy_map.get('deploy_status') == 'FAILED'

        promote_to_preprod = re.match('promote-to-preprod', deployment_data.operation)
        promote_to_stage = re.match('promote-to-stage', deployment_data.operation)
        run_tests_operation = re.match('run-tests', deployment_data.operation)

        if not rollback_enabled:
            run_tests_smoke = False
        elif run_tests_operation and test_included:
            run_tests_smoke = True
        elif not any([promote_to_stage, env_sync_job]):
            skip_smoke = deployment_data.quality.get('skip_smoke') and not promote_to_preprod
            rollback_scenario = deploy_map.get('rollback', False) # deploy failure & rollback available
            critical_fail = deployment_data.post_deploy.get('critical_fail', False) # critical test failure
            version_deployed = True if all([
                deployment_data.deploy.get('version_deployed'),
                skip_smoke, not promote_to_preprod]) else False # version already deployed
            run_tests_smoke = all([smoke_tests]) and \
                not any([deploy_fail, critical_fail, skip_smoke, rollback_scenario, version_deployed])
        elif all([promote_to_stage, smoke_tests]):
            run_tests_smoke = True
        else:
            run_tests_smoke = False # quality check failed

        if run_tests_smoke: # set vault map for smoke tests
            vault_map = yaml.safe_load(aem_deploy_env).get('vault_map',{}).get(deploy_env) if aem_deploy_env else None
            set_output('vault-map', json.dumps(vault_map))
        run_tests_regression = auto_deploy_map and deploy_env in auto_deploy_map.get('regression',[])
        run_dod_checks = auto_deploy_map and deploy_env in auto_deploy_map.get('dod_envs',[])
        run_tests['smoke'] = run_tests_smoke
        run_tests['regression'] = run_tests_regression
        run_tests['dod'] = run_dod_checks
        run_tests['qtest_folder'] = auto_deploy_map.get('qtest_folder','') if auto_deploy_map else ''
        logger.info(f'Run post-deploy tests on {deployment_data.name}: {json.dumps(run_tests)}')
        set_output('run-tests', json.dumps(run_tests))
        return deployment_data
    except (KeyError, AttributeError, RuntimeError) as e:
        raise RuntimeError(f'Error checking deploy map: {e}') from e


def post_deploy_test(deployment_data):
    """
    Post-deploy update of deployment data map - evaluate rollback scenario based on test results.
    This will set the 'post_deploy' block of the deployment data map.
    """
    try:
        test_result = os.getenv('TEST_RESULT') or 'SKIPPED'
        regression_result = os.getenv('REGRESSION_RESULT') or 'SKIPPED'
        p1_tag_result = os.getenv('P1_RESULT') or 'SKIPPED'
        target_tag_result = os.getenv('TARGET_RESULT') or 'SKIPPED'

        p1_result,  p1_total_tests = '', 0
        target_result, target_total_tests = '', 0

        quality_map = deployment_data.quality
        rollback_map = deployment_data.deploy_package.get('module_values_rollback', {})
        deploy_map = deployment_data.deploy
        deploy_status = deploy_map.get('deploy_status')
        
        if p1_tag_result and 'SKIPPED' not in p1_tag_result:
            p1_result, p1_total_tests = get_property(p1_tag_result, deployment_data.env)
        if target_tag_result and 'SKIPPED' not in target_tag_result:
            target_result, target_total_tests = get_property(target_tag_result, deployment_data.env)
        logger.info(f"p1_result: {p1_result} p1_total_tests: {p1_total_tests} --- target_result: {target_result} target_total_tests: {target_total_tests}")

        deployment_data.post_deploy['test_result'] = test_result
        deployment_data.post_deploy['p1_result'] = p1_tag_result
        deployment_data.post_deploy['target_result'] = target_tag_result
        deployment_data.post_deploy['p1_total_tests'] = p1_total_tests
        deployment_data.post_deploy['target_total_tests'] = target_total_tests
        deployment_data.post_deploy['p1_status'] = p1_result
        deployment_data.post_deploy['target_status'] = target_result
        deployment_data.post_deploy['regression_result'] = regression_result

        build_success = not any([
            re.match('FAILURE|fail', test_result),
            re.match('FAILED', deploy_status),
            re.match('fail', p1_result),
            re.match('fail', target_result),
            quality_map.get('critical_fail', False)
        ])
        rollback_scenario = bool(rollback_map) and not any([build_success, deploy_map.get('rollback', False)])
        if re.match('run-tests|deploy-to-dev|ams-code-quality|promote-to-stage', deployment_data.operation) or not quality_map.get('autorollback_enabled'):
            rollback_scenario = False

        if build_success:
            deployment_data.post_deploy['overall_status'] = 'success'
            if deployment_data.operation == 'promote-to-stage':
                deployment_data.post_deploy['comments'] = f"Deployment successful for {deployment_data.name} in {deployment_data.env}."
        else:
            deployment_data = get_status_and_message(deployment_data, rollback_scenario)

        deployment_data.deploy['rollback'] = rollback_scenario
        if rollback_scenario:
            rollback_output = rollback_map.copy()
            rollback_output['name'] = deployment_data.name
            logger.info(f'Rollback map: {json.dumps(rollback_output)}')
            set_output('rollback-map', json.dumps(rollback_output))
        logger.info(f'Rollback scenario: {rollback_scenario}')
        set_output('rollback-scenario', rollback_scenario)

        return deployment_data
    except RuntimeError as e:
        raise RuntimeError(f'Error setting post deploy map: {e}') from e


def get_property(env_property, deploy_env):
    if isinstance(env_property, str):
        env_property = [env_property]  
    for env in env_property:
        env_key, *values = env.split('~')
        if env_key == deploy_env:
            result = values[0] if len(values) > 0 else None
            total_tests = values[1] if len(values) > 1 else None
            return result, total_tests
    return None, None


def get_status_and_message(deployment_data, rollback_scenario):
    try:
        test_url = os.getenv('TEST_URL','N/A')
        rollback_map = deployment_data.deploy_package.get('module_values_rollback', {})
        deploy_map = deployment_data.deploy
        rollback_enabled = deployment_data.quality.get('autorollback_enabled')

        # set failure status
        overall_status = 'failure'
        if deploy_map.get('deploy_status') == 'FAILED':
            msg = deployment_data.post_deploy.get('comments', 'Deployment failed. ')
        else:
            msg = f'Post deployment test(s) failed. '
            # set failure message
            if not rollback_map:
                msg += f'Rollback package was not found or no rollback for operation: {deployment_data.operation}. '
                overall_status = 'skipped_rollback'
            elif not rollback_enabled:
                msg += f'Rollback disabled.'
                overall_status = 'skipped_rollback'
            elif rollback_map and rollback_scenario:
                overall_status = 'rollback'
                if deploy_map.get('rollback_path'):
                    msg += f"Rolled back to version {rollback_map['artifact_version']}. "
                    deployment_data.deploy['rollback'] = True
            else:
                msg += 'No rollback for lower environments, stage or prod. '
                overall_status = 'skipped_rollback'
        
        # set post deploy map
        deployment_data.post_deploy['comments'] = msg
        deployment_data.post_deploy['overall_status'] = overall_status
        if test_url:
            test_urls = test_url.split(',')
            deployment_data.post_deploy['test_url'] = test_urls[0]
            if len(test_urls) > 1:
                deployment_data.post_deploy['regression_test_url'] = test_urls[1]
        return deployment_data
    except (KeyError, AttributeError, Exception) as e:
        logger.error(f"Error setting report status: {e} - {traceback.format_exc()}")
        raise RuntimeError(f'Error setting report status: {e}') from e


def set_deploy_data(deployment_data):
    post_deploy = deployment_data.post_deploy
    deploy_package = deployment_data.deploy_package
    deploy_env = deployment_data.env
    auto_deploy = deploy_package.get('cd_deploy')
    deploy_env = yaml.safe_load(os.getenv('AEM_CHECK_ENV_MAP', '{}')).get(deploy_env, deploy_env).lower()
    deploy_props = {'DEPLOY':deploy_env, 'LAST_DEPLOYED_ENV':deploy_env}
    if auto_deploy:
        if deployment_data.auto_deploy.get('env_name') == 'PREPROD':
            deployment_data = check_subtask_results(deployment_data)
        if post_deploy.get('overall_status') == 'success' and re.match('pass|SUCCESS', str(post_deploy.get('test_result'))):
            deploy_props['CONTINUOUS_DEPLOY'] = deploy_env
    if auto_deploy or deployment_data.deploy:
        set_output('deploy-props', json.dumps(deploy_props))
    return deployment_data
  

def set_output(key, value):
    """set output for GitHub Actions"""
    if value is not None:
        os.system(f"echo '{key}={value}' >> $GITHUB_OUTPUT")
    else:
        logger.warning(f"Output {key} is None, skipping.")


def check_subtask_results(deployment_data):
    subtask_details = {}
    st_status = False
    post_deploy = deployment_data.post_deploy
    p1_result = post_deploy.get('p1_result', 'SKIPPED')
    p1_status = post_deploy.get('p1_status', 'SKIPPED')
    p1_total_tests = post_deploy.get('p1_total_tests', 'SKIPPED')
    target_result = post_deploy.get('target_result', 'SKIPPED')
    target_status = post_deploy.get('target_status', 'SKIPPED')
    target_total_tests = post_deploy.get('target_total_tests', 'SKIPPED')
    test_results_comment = f"P1 tests: {p1_status} ({p1_total_tests} tests). " \
        f"Target tests: {target_status} ({target_total_tests} tests). "
    if 'pass' in p1_result and 'pass' in target_result:
        st_status = True
    subtask_details.update({'st_status': st_status, 'comment': test_results_comment})
    deployment_data.quality.get('jira_subtask_updates').update({'preprod_validation': subtask_details})
    return deployment_data
