import os
import sys
import yaml
import copy
import utils.prechecks as prechecks
from kpghalogger import KpghaLogger
logger = KpghaLogger()

COLOR_RED = "\u001b[31m"


def main():
    """
    Main function that executes the appropriate operation based on the value of the 'operation' environment variable.
    """
    try:
        operation = os.getenv('OPERATION')
        deploy_env = os.getenv('DEPLOY_ENV')
        gh_context_env = os.getenv('GH_CONTEXT')
        gh_context = yaml.safe_load(gh_context_env) if gh_context_env and gh_context_env != 'null' else {}
        if operation == 'update-deploy':
            deploy_map = yaml.safe_load(sys.argv[1]) if len(sys.argv) > 1 else {}
            update_deploy_map(deploy_map, gh_context)
        elif operation == 'critical-tests':
            critical_test(deploy_env, gh_context)
        elif artifact_manifest := gh_context.get('aem-manifest', '').replace('.json', '').strip(): # manifest flow only
            if operation == 'parallel-manifest':
                prechecks.set_parallel_manifest(artifact_manifest, gh_context)
            else:
                manifest_env = prechecks.set_manifest(artifact_manifest, gh_context)
                critical_test(manifest_env, gh_context)
    except RuntimeError as e:
        logger.error(f"Error in aem utils: {e}")
        raise RuntimeError(f'Error in aem utils: {e}') from None


def critical_test(deploy_env, gh_context):
    """
    Function to perform critical tests based on the deploy environment and the skip-critical flag in the GitHub context.
    """
    critical_envs = list(yaml.safe_load(os.getenv('CONTROL_TOWER_ENVS', '[]')))
    aem_manifest = yaml.safe_load(os.getenv('AEM_MANIFEST') or '{}')
    skip_critical = gh_context.get('skip-critical') == 'true' if gh_context else False
    if os.getenv('GITHUB_REPOSITORY') == 'CDO-KP-ORG/ams-manifest-sync':
        critical_test = False
    elif deploy_env in critical_envs and not skip_critical:
        critical_test = True
    else:
        critical_test = False
    if aem_manifest.get('critical') == 'False': # pipeline properties global disable
        critical_test = False
    os.system(f"echo 'critical-tests={critical_test}' >> $GITHUB_OUTPUT")
    logger.info(f'Require critical regression tests in environment {deploy_env}: {critical_test}')


def update_deploy_map(deploy_map, gh_context):
    """
    Function to update the deploy map based on the provided deploy map and GitHub context.
    """
    repo_name = os.getenv('GITHUB_REPOSITORY')
    workspace = os.getenv('GITHUB_WORKSPACE')
    cdo_kp_org_aem = os.getenv('GHA_ORG') == 'CDO-KP-ORG'
    ci_deploy = deploy_map.get('ci_deploy')
    auto_deploy = deploy_map.get('cd_deploy')
    repo_deploy_env = deploy_map.get('deploy_environment')
    with open(f"{os.getenv('PROPS_PATH')}/ansible/inventory/nonprod", "r+") as aem_env_file:
        aem_env_props = yaml.safe_load(aem_env_file)
    if ci_deploy:
        if auto_deploy:
            # remove environments already deployed to successfully
            repo_envs = ['DEV','QA']
            auto_deploy_envs = deploy_map.get('auto_deploy_map',{}).get('jiraDetails',{}).get('environments',{})
            repo_deploy_envs = [env.strip() for sublist in [v.split(',') for k, v in auto_deploy_envs.items() if k.upper() in repo_envs] for env in sublist]
            if not repo_deploy_envs:
                raise ValueError(f'{COLOR_RED}No {", ".join(repo_envs)} environments found in auto_deploy_map. Please add at least 1 lower environment in RRC.')
            # remove already deployed environments from list
            repo_deploy_env = [i for i in repo_deploy_envs if i not in deploy_map['cd_jira_envs']]
            if not repo_deploy_env:
                repo_deploy_env = [repo_deploy_envs[-1]]
            if not deploy_map['module_values_deploy']['artifact_version'].endswith('snapshot'):
                deploy_map['security_scan'] = True
        else:
            aem_ci_envs = list(aem_env_props.get('dev').get('hosts').keys()) + list(aem_env_props.get('qa').get('hosts').keys()) + list(aem_env_props.get('hint').get('hosts').keys())
            deploy_environments = copy.copy(deploy_map['deploy_environment'])
            for ci_env in deploy_map['deploy_environment']:
                if ci_env not in aem_ci_envs and cdo_kp_org_aem:
                    deploy_environments.remove(ci_env)
                if len(deploy_environments) == 0:
                    logger.info('No valid CI environments selected.')
                    return
                else:
                    repo_deploy_env = deploy_environments
    # support for deploy-to operation
    operation = gh_context.get('operation') if gh_context else None
    deploy_env_list = operation.split('deploy-to-')[1] if operation and operation.startswith('deploy-to') else ''
    for env in repo_deploy_env:
        if deploy_env_list and not auto_deploy and env not in aem_env_props.get(deploy_env_list).get('hosts').keys() and cdo_kp_org_aem:
            raise ValueError(f'{COLOR_RED}Environment {env} is not in AEM {deploy_env_list} environments. Please choose correct environment from https://confluence-aes.kp.org/x/Hz7CRQ')
        elif deploy_env_list and not auto_deploy and env in yaml.safe_load(os.getenv('CONTROL_TOWER_ENVS', '[]')) and cdo_kp_org_aem:
            raise ValueError(f'{COLOR_RED}Environment {env} is a controlled environment. Please choose environment from	https://confluence-aes.kp.org/x/Hz7CRQ')
    # update map
    deploy_map['name'] = repo_name.split('/')[1]
    deploy_map['deploy_environment'] = repo_deploy_env
    deploy_map['aem_vault'] = prechecks.set_repo(deploy_map, deploy_env_list)
    logger.info(yaml.safe_dump(deploy_map, indent=2, default_flow_style=False))
    with open(f'{workspace}/cicd/cd_map.yml', 'w+') as f:
        f.write(yaml.safe_dump(deploy_map))


if __name__ == "__main__":
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "start"}}))
    main()
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))
