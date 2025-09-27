"""set maps for AEM repo and manifest flows"""
import copy
import os
import json
import re
import yaml
from kpghalogger import KpghaLogger
logger = KpghaLogger()

workspace = os.getenv('GITHUB_WORKSPACE')


def set_repo(deploy_map, deploy_env_list):
    """Set properties for the AEM repository flow"""
    auto_deploy = deploy_map.get('cd_deploy')
    deploy_environments = create_environment_map(deploy_map, 'repo', deploy_env_list, auto_deploy)
    deploy_version = deploy_map.get('module_values_deploy').get('artifact_version')
    control_tower_envs = list(yaml.safe_load(os.getenv('CONTROL_TOWER_ENVS', '[]')))
    if 'snapshot' in deploy_version:
        if intersection := list(set(deploy_environments).intersection(control_tower_envs)):
            raise RuntimeError(f'Deploying SNAPSHOT to {intersection} not permitted.')
    return create_vault_map(deploy_environments)


def set_manifest(aem_manifest, gh_context):
    """Set properties for the AEM manifest flow."""
    try:
        context = 'manifest'
        manifest_records = _load_manifest_records(aem_manifest)
        sorted_records = sort_records(manifest_records)
        aem_manifest_name = sorted_records.get('manifest') or gh_context.get('aem-manifest', '')

        operation = gh_context.get('operation', '')
        deploy_env = _determine_deploy_env(gh_context, aem_manifest_name)
        context = _determine_context(gh_context, operation)

        deploy_packages = _process_packages(manifest_records['products'], operation)
        auto_deploy = all(pkg.get('cd_deploy', False) for pkg in deploy_packages)
        
        _handle_dispatcher_package(deploy_packages, operation)
        
        create_environment_map(deploy_packages, context, deploy_env, auto_deploy, operation, aem_manifest_name)
        os.system(f"echo 'deploy-packages={json.dumps(deploy_packages)}' >> $GITHUB_OUTPUT")
        logger.info(f'Packages: \n{json.dumps(deploy_packages, indent=2)}')

        test_artifacts = manifest_records.get('test-artifacts', [])
        os.system(f"echo 'test-artifacts={json.dumps(test_artifacts)}' >> $GITHUB_OUTPUT")
        return deploy_env
    except (FileNotFoundError, IndexError, RuntimeError) as e:
        raise RuntimeError(f'Error setting manifest - confirm {aem_manifest_name} exists in repo: {e}.') from None


def _load_manifest_records(aem_manifest):
    """Load manifest records from environment and files."""
    if os.getenv('MANIFEST_RECORDS'):
        manifest_records = yaml.safe_load(os.getenv('MANIFEST_RECORDS', '{}'))
    else:
        with open(f'{workspace}/aem-manifests/{aem_manifest}.json', 'r+', encoding='utf-8') as f:
            manifest_records = yaml.safe_load(f)

    return manifest_records


def _determine_deploy_env(gh_context, aem_manifest_name):
    """Determine the deployment environment."""
    operation = gh_context.get('operation', '')
    deploy_env = os.getenv('DEPLOY_ENV')
    context_env = gh_context.get('environment', None)

    if context_env and not operation:
        deploy_env = context_env.lower().replace('-', '')
        logger.info(f'Context environment {deploy_env}')
    elif deploy_env:
        logger.info(f'AMS deploy - deploy environment {deploy_env}')
    elif aem_manifest_name.lower().startswith('kp.org'):
        logger.info('Preprod/Prod manifest flow')
    else:
        year_match = re.search(r'-(\d{4})-', aem_manifest_name)
        year = year_match.group(0)
        manifest_env = aem_manifest_name.lower().split('kp.org-')[1].split(year)[0].replace('-','')
        deploy_env = yaml.safe_load(os.getenv('AEM_CHECK_ENV_MAP', '{}')).get(manifest_env, manifest_env)
        logger.info(f'AEM deploy - deploy environment {deploy_env}')
    
    return deploy_env


def _determine_context(gh_context, operation):
    """Determine the context based on environment and operation."""
    context_env = gh_context.get('environment', None)
    if context_env and not operation:
        return 'manifest' if gh_context.get('skip-critical') else 'env-sync'
    return 'manifest'


def _process_packages(products, operation):
    """Process and transform package data."""
    deploy_packages = products
    for deploy_package in deploy_packages:
        _transform_package(deploy_package, operation)
    return deploy_packages


def _transform_package(deploy_package, operation):
    """Transform a single package to the required format."""
    package_version = deploy_package['version']
    package_name = deploy_package['name']
    auto_deploy = deploy_package.get('cd_deploy', False)
    
    # Extract version components
    if '-snapshot' in package_version.lower():
        deploy_version = '-'.join(package_version.split('-')[-2:])
    else:
        deploy_version = package_version.split('-')[-1]
    
    deploy_id = deploy_package.get('version').split(f"-{deploy_version}")[0]
    rollback_version = deploy_package.get('rollbackVersion').replace(f'{deploy_id}-','')
    rollback_id = deploy_package.get('rollbackVersion').split(f"-{rollback_version}")[0]
    
    action = deploy_package.get('action')
    force_deploy = deploy_package.get('forceDeploy','').lower() == 'true' or auto_deploy
    
    # Build module objects
    deploy_module = _build_deploy_module(deploy_package, deploy_id, deploy_version, operation)
    rollback_module = _build_rollback_module(rollback_id, rollback_version, deploy_module)
    test_module = _build_test_module(deploy_id, deploy_version)
    jira_props = _build_jira_props(deploy_package)
    
    # Clear and rebuild package
    deploy_package.clear()
    deploy_package.update({
        'name': package_name,
        'action': action,
        'force_deploy': force_deploy,
        'jira': jira_props,
        'module_values_deploy': deploy_module,
        'module_values_rollback': rollback_module,
        'module_values_test': test_module,
        'cd_deploy': auto_deploy
    })


def _build_deploy_module(deploy_package, deploy_id, deploy_version, operation=None):
    """Build deploy module configuration."""
    secondary = deploy_package.get('secondary', {})
    secondary_ids = []
    
    # Add content ID for promote-to-preprod operation
    if operation == 'promote-to-preprod':
        if content_id := secondary.get('content_id'):
            secondary_ids.append(content_id + ':' + secondary.get('content_version', ''))
    
    secondary_ids.extend(secondary.get('secondary_ids', []))
    
    return {
        'artifact_id': deploy_id,
        'artifact_version': deploy_version,
        'secondary_ids': secondary_ids
    }


def _build_rollback_module(rollback_id, rollback_version, deploy_module):
    """Build rollback module configuration."""
    return {
        'artifact_id': rollback_id,
        'artifact_version': rollback_version,
        'secondary_ids': copy.copy(deploy_module['secondary_ids'])
    }


def _build_test_module(deploy_id, deploy_version):
    """Build test module configuration."""
    return {
        'artifact_id': deploy_id.replace('.ui.apps','*.it.tests'),
        'artifact_version': deploy_version
    }


def _build_jira_props(deploy_package):
    """Build JIRA properties dictionary."""
    return {
        'jira_id': deploy_package.get('jiraTicketId'),
        'jira_project': deploy_package.get('jiraProjectId'),
        'jira_fix': deploy_package.get('jiraFixVersion'),
        'jira_reporter': deploy_package.get('jiraReporterEmail')
    }


def _handle_dispatcher_package(deploy_packages, operation):
    """Handle dispatcher package extraction and removal."""
    for deploy_package in deploy_packages[:]:  # Use slice copy for safe iteration
        if (deploy_package.get('name') == 'ams-configs' and 
            not re.match('promote-to-stage|promote-to-prod', operation)):
            if deploy_package.get('action') == 'install':
                logger.info(f'Dispatcher Package: \n{json.dumps(deploy_package, indent=2)}')
                os.system(f"echo 'dispatcher-package={json.dumps(deploy_package)}' >> $GITHUB_OUTPUT")
            deploy_packages.remove(deploy_package)


def sort_records(manifest_records):
    """
    Create a mapping from product name to product dict
    Build the new ordered list, keeping only products that exist in the manifest
    Add any products not in the order list, preserving their original order
    """
    manifest_order = yaml.safe_load(os.getenv('AEM_CD_MANIFEST_ORDER') or '[]')
    product_map = {p["name"]: p for p in manifest_records["products"]}
    ordered_products = [product_map[name] for name in manifest_order if name in product_map]
    remaining_products = [p for p in manifest_records["products"] if p["name"] not in manifest_order]
    manifest_records["products"] = ordered_products + remaining_products
    return manifest_records


def create_environment_map(deploy_map, context, deploy_env, auto_deploy, operation=None, manifest_name=None):
    """Create a map to use for matrix strategies.

    Args:
        deploy_map (dict): The deployment map.
        context (str): The context ('repo' or 'manifest').
        deploy_env (str): The deployment environment(s).
        operation (str, optional): The operation. Defaults to None.

    Returns:
        list: The list of deployment environments.
    """
    skip_build = False
    if context == 'repo':
        deploy_environments = list(deploy_map.get('deploy_environment'))
        if auto_deploy:
            skip_build = True if deploy_map.get('cd_jira_ticket') else False
            deploy_environments = ['preprod'] if len(deploy_environments) == 0 else deploy_environments # default to preprod if no deploy envs specified - used for ams-configs
    else:
        deploy_envs = yaml.safe_load(deploy_env)
        if isinstance(deploy_envs, list):
            deploy_environments = [ deploy_envs ]
        elif deploy_envs:
            deploy_environments = [ x.strip() for x in deploy_envs.split(',') ]
        else:
            deploy_environments = ['kpoi2'] # pr environment

    # approval environment
    deploy_check_env = ''
    if re.match('promote-to-stage|promote-to-prod', str(operation)):
        deploy_check_env = operation.split('promote-to-')[1]
    elif context == 'manifest' and not any([auto_deploy, re.match('run-tests|akamai', str(operation)), os.getenv('GITHUB_EVENT_NAME') == 'pull_request']):
        deploy_check_env = deploy_environments[0]
    elif context == 'env-sync':
        deploy_check_env = 'prod'

    deploy_environment = {}
    deploy_environment['envs'] = deploy_environments
    deploy_environment['jobs'] = 1 # len(deploy_environments) to allow parallel deployments
    deploy_environment['packages'] = len(deploy_map) if context == 'manifest' else 1
    deploy_environment['deployenv'] = deploy_check_env
    if re.match('manifest|env-sync', context): # only used in manifest flows
        deploy_environment['vault_map'] = create_vault_map(deploy_environments)
        deploy_environment['manifest'] = manifest_name
        if auto_deploy:
            os.system(f"echo '### :information_source: Manifest Name: {manifest_name}' >> $GITHUB_STEP_SUMMARY")
    else:
        deploy_environment['name'] = deploy_map['name']
        if auto_deploy:
            deploy_environment['skip_build'] = skip_build
    logger.info(f'Deploy environment: \n{yaml.safe_dump(deploy_environment, indent=2, sort_keys=False)}')
    os.system(f"echo 'deploy-environment={json.dumps(deploy_environment, sort_keys=False)}' >> $GITHUB_OUTPUT")
    return deploy_environments


def set_parallel_manifest(artifact_manifest, gh_context):
    manifests = [ x.strip() for x in artifact_manifest.split(',') ]
    deploy_environment = {}
    deploy_environment['manifests'] = manifests
    deploy_environment['jobs'] = int(gh_context.get('max-parallel'))
    logger.info(f'Deploy environment: \n{yaml.safe_dump(deploy_environment, indent=2)}')
    os.system(f"echo 'deploy-environment={json.dumps(deploy_environment, sort_keys=False)}' >> $GITHUB_OUTPUT")

  
def create_vault_map(deploy_environments):
    """Create a deployment map for the environments.
       Used only for staging and production deployments.

    Args:
        deploy_environments (list): The list of deployment environments.

    Returns:
        dict: The deployment map.
    """
    deploy_map = {}
    try:
        for env in [x.lower() for x in deploy_environments]:
            env_map = {}
            if 'az-' not in env:
                env = env.replace('-', '')
            with open(f"{os.getenv('PROPS_PATH')}/ansible/inventory/host_vars/{env}/aem_vars.yml", "r+") as aem_env_file:
                aem_env_props = yaml.safe_load(aem_env_file)
            aem_env_file.close()
            aem_author = aem_env_props.get('aem_author')
            server_protocol = 'http' if 'http_port' in aem_author.keys() else 'https'
            aem_author_ip = aem_author.get('server_ip')[0]
            aem_author_port = f":{aem_author.get(f'{server_protocol}_port')}" if aem_author.get(f'{server_protocol}_port') else ''
            aem_author_server = server_protocol + '://' + aem_author_ip + aem_author_port

            aem_publisher = aem_env_props.get('aem_publisher')
            aem_publisher_ip = aem_publisher.get('server_ip')[0]
            aem_publisher_port = f":{aem_publisher.get(f'{server_protocol}_port')}" if aem_publisher.get(f'{server_protocol}_port') else ''
            aem_publisher_server = server_protocol + '://' + aem_publisher_ip + aem_publisher_port
            
            env_map['aem_author'] = aem_author_server
            env_map['aem_publisher'] = aem_publisher_server
            deploy_map[env] = env_map
    except FileNotFoundError as e:
        logger.info(f'No vault map created - confirm environment exists if applicable: {e}')
    return deploy_map
