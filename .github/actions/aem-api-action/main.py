"""aem api action"""
import os
import json
import yaml
from dataclasses import dataclass, asdict
from typing import Optional
from packaging.version import Version
from utils import api_utils
from kpghalogger import KpghaLogger

logger = KpghaLogger()
workspace = os.getenv('GITHUB_WORKSPACE')
operation = os.getenv('OPERATION')
manifest_deploy = bool(os.getenv('MANIFEST_DEPLOY'))


@dataclass
class DeploymentPackage:
    """Data structure to hold deployment package information"""
    action: Optional[str] = None
    name: Optional[str] = None
    module_values_deploy: Optional[dict] = None
    module_values_rollback: Optional[dict] = None
    deploy_artifacts: Optional[list] = None
    primary: Optional[str] = None
    force_deploy: Optional[bool] = True
    path: Optional[dict] = None
    
    @classmethod
    def from_dict(cls, data: dict) -> 'DeploymentPackage':
        """Create DeploymentPackage instance from dictionary (normal deployment flow)"""
        return cls(
            action=data.get('action'),
            name=data.get('name'),
            module_values_deploy=data.get('module_values_deploy'),
            module_values_rollback=data.get('module_values_rollback'),
            deploy_artifacts=data.get('deploy_artifacts'),
            primary=data.get('primary'),
            path=data.get('path'),
            force_deploy=data.get('force_deploy', True)
        )
    
    @classmethod
    def on_demand(cls, package: dict) -> 'DeploymentPackage':
        """Create DeploymentPackage instance for on-demand rollback flow"""
        artifact_id = package.get('artifact_id')
        return cls(
            action='deploy',
            name=package.get('name'),
            module_values_deploy={
                'artifact_id': artifact_id,
                'artifact_version': package.get('artifact_version'),
                'result': False
            },
            deploy_artifacts=[artifact_id],
            primary=artifact_id,
            path=package.get('path')
        )

@dataclass
class DeploymentData:
    """Data structure to hold deployment information"""
    deploy_status: Optional[str] = None
    rollback: Optional[bool] = None
    version_deployed: Optional[bool] = None
    path: Optional[str] = None
    content_path: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary, excluding None values"""
        return {k: v for k, v in asdict(self).items() if v is not None}


def main():
    """main function"""
    package = yaml.safe_load(os.getenv('DEPLOY_PACKAGE') or '{}')

    if operation and operation.casefold() == 'confirm-status':
        api_utils.run_confirm_status(package)

    deploy_env = os.getenv('DEPLOY_ENV')
    artifact_paths = json.loads(os.getenv('ARTIFACT_PATH')) # local path to package
    vault_map = yaml.safe_load(os.getenv('VAULT_MAP', '{}'))

    deployment_data_map = get_deploy_data(package['name'], deploy_env)

    # Support both normal deployment and on-demand rollback flows
    deploy_package_dict = deployment_data_map.get('deploy_package', {})
    rollback_flow = deploy_package_dict.get('action') == 'rollback' or operation == 'rollback'
    if deploy_package_dict:
        # Normal deployment flow: use existing package_deploy_map.yml
        deploy_package = DeploymentPackage.from_dict(deploy_package_dict)
    else:
        # On-demand flow: construct from external data source
        deploy_package = DeploymentPackage.on_demand(package)

    # Initialize deployment data from existing data or create new instance
    rollback_package = deploy_package.module_values_rollback
    existing_deploy_data = deployment_data_map.get('deploy', {})
    deployment_data = DeploymentData(
        deploy_status=existing_deploy_data.get('deploy_status'),
        rollback=existing_deploy_data.get('rollback'),
        version_deployed=existing_deploy_data.get('version_deployed')
    )
        
    try:
        for value in vault_map.values(): # iterative deployment to each server
            deploy_aem_packages(value, deploy_package, deploy_env, artifact_paths, rollback_flow, deployment_data)
    except RuntimeError as e: # deploy failure scenario
        deployment_data.deploy_status = 'FAILED'
        deployment_data.rollback = rollback_package
        logger.error(f'Error in deploy: {e}')
    finally:
        if deployment_data_map and not rollback_flow:
            post_deploy_aem_packages(deployment_data_map, vault_map, deployment_data, rollback_package, rollback_flow)


def deploy_aem_packages(value, deploy_package: DeploymentPackage, deploy_env, artifact_paths, rollback_flow, deployment_data: DeploymentData):
    """delete, upload and install packages"""
    aem_creds = value.get('aem_creds')
    env_details_path = {}
    for k,v in artifact_paths.items():
        env_details_path[k] = v    
    for server in value.get('server'): # iterate through author and publisher servers
        for deploy_artifact in deploy_package.deploy_artifacts or []: # iterate through components (multiple for spa apps)
            logger.info(
                f'Deploying {deploy_artifact} in {deploy_env} server {server}'
            )
            deploy_aem_package(deploy_artifact, deploy_package, env_details_path, server, aem_creds, rollback_flow, deployment_data)


def deploy_aem_package(deploy_artifact, deploy_package: DeploymentPackage, env_details_path, server, aem_creds, rollback_flow, deployment_data: DeploymentData):
    """delete, check version, upload, and install package"""
    try:
        current_version = True if rollback_flow else (deploy_package.module_values_rollback or {}).get('artifact_version')
        primary_package = deploy_artifact == deploy_package.primary
        force_deploy = deploy_package.force_deploy
        content_package = '.content' in deploy_artifact
        uninstall_flow = operation == 'uninstall'

        path_to_package = env_details_path.get(deploy_artifact)
        existing_package_path = deploy_package.path.get(deploy_artifact)

        # check duplicate version
        skip_deploy = False
        if uninstall_flow:
            skip_deploy = True
            if existing_package_path:
                api_utils.delete_package(existing_package_path, aem_creds, server)
            else:
                logger.info(f'No existing package found on {server}')
        if all([existing_package_path, primary_package, current_version]) and not any([rollback_flow, uninstall_flow]):
            package_version = (deploy_package.module_values_deploy or {}).get('artifact_version')
            version_deployed = check_existing_version(current_version, package_version)
            deployment_data.version_deployed = version_deployed
            if version_deployed and not force_deploy:
                logger.info(
                    f'Found same or higher version already deployed on {server}. '
                    f'Previous version: {current_version}'
                )
                skip_deploy = True

        # delete existing package and install new one
        if skip_deploy:
            deployment_data.deploy_status = 'SKIPPED'
        elif content_package and rollback_flow:
            logger.info(f'Deleting content package on rollback: {deploy_artifact}')
            api_utils.delete_package(existing_package_path, aem_creds, server)
        else:
            # upload package
            upload_path = api_utils.upload_package(aem_creds, path_to_package, server)
            deploy_package.path[deploy_artifact] = upload_path
            if all([current_version, existing_package_path, existing_package_path != upload_path]):
                logger.info(f'Install Flow. Deleting the previous package: {existing_package_path}')
                api_utils.delete_package(existing_package_path, aem_creds, server)
            # install package
            api_utils.install_package(aem_creds, upload_path, server)
    except RuntimeError as e:
        raise RuntimeError(f'Error in deploy package {e}') from None


def post_deploy_aem_packages(deployment_data_map, vault_map, deployment_data: DeploymentData, rollback_package, rollback_flow):
    """Handle post-deployment tasks including wait time checks and output generation"""
    try:
        updated_deployment_data = api_utils.check_wait_time(deployment_data_map, vault_map, deployment_data.to_dict(), rollback_package)
        # Update the dataclass instance with any changes from check_wait_time
        deployment_data.__dict__.update(updated_deployment_data)
        deployment_data_map['deploy'] = deployment_data.to_dict()

        logger.info(f'Rollback scenario: {deployment_data.rollback}')
        logger.info(f'Deployment data:\n{json.dumps(deployment_data_map, indent=2)}')

        with open(f'{workspace}/package_deploy_map.json', 'w+', encoding='utf-8') as f:
            json.dump(deployment_data_map, f, indent=2)

        os.system(f"echo 'rollback-scenario={deployment_data.rollback}' >> $GITHUB_OUTPUT")
        os.system(f"echo 'deployment-data={json.dumps(deployment_data_map)}' >> $GITHUB_OUTPUT")
    except RuntimeError as e:
        logger.error(f'Error setting deploy rollback and artifact info: {e}')


def get_deploy_data(package_name, deploy_env):
    """read deployment data from package map in workspace"""
    try:
        local_path = f'{workspace}/package_deploy_map.json'
        if os.path.exists(local_path):
            package_path = local_path
        else:
            package_path = f'{workspace}/deploy-results-{package_name}-{deploy_env}/package_deploy_map.json'
        with open(package_path, 'r', encoding="utf-8") as a:
            deployment_data = json.load(a)
        return deployment_data
    except (FileNotFoundError, UnboundLocalError, Exception) as e:
        logger.info(f'No existing deployment data found: {e}')
        return {}


def check_existing_version(current_version, package_version):
    """check if existing version is new than deploy version"""
    try:
        duplicate_package = False
        remove_snapshot = lambda version: version.lower().replace('-snapshot','').replace('-release','').split('-')[-1]
        existing_version = remove_snapshot(current_version)
        package_version = remove_snapshot(package_version)
        logger.info(f'Existing version: {existing_version}')
        logger.info(f'Package version: {package_version}')
        duplicate_package = Version(existing_version) >= Version(package_version)
        return duplicate_package
    except Exception as e:
        logger.error(f'Error checking existing version: {e}')
        return False


if __name__ == "__main__":
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "start"}}))
    main()
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))
