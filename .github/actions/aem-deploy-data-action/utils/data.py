"""create deployment data map used for reporting"""
import os
import re
import json
import yaml
import pytz
import hashlib
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import datetime
from kpghalogger import KpghaLogger
logger = KpghaLogger()

workspace = os.getenv('GITHUB_WORKSPACE')
artifact_props = yaml.safe_load(os.getenv('ARTIFACTORY_PROP') or '{}')

@dataclass
class DeployContext:
    """Context for deployment, including environment and operation."""
    env: str = ''
    operation: str = 'N/A'
    manifest_deploy: bool = False
    dispatcher_deploy: bool = False
    deploy_package: Optional[dict] = None
        
@dataclass
class QualityProperties:
    sonar: str = "N/A"
    sonar_date: str = "N/A"
    autorollback: str = "N/A"
    autorollback_date: str = "N/A"
    autorollback_enabled: bool = False
    regression: str = "N/A"
    regression_date: str = "N/A"
    regression_pass: str = "N/A"
    regression_enabled: bool = False
    ams: str = "N/A"
    skip_critical: bool = False
    skip_smoke: bool = False
    sre_slo_id: str = "N/A"
    synthetic_id: str = "N/A"
    nexus_id: str = ""
    checkmarx_id: str = ""
    branch: str = ""
    appsec_fail: bool | str = False
    critical_pre: Optional[int] = None
    core_name: Optional[str] = None
    quality_fail: bool = False
    jira_subtask_updates: Optional[Dict[str, Any]] = field(default_factory=dict)
    context: DeployContext = field(default_factory=DeployContext, repr=False)

    def __post_init__(self):
        """Initialize quality properties from environment variables and artifact properties."""
        if self.context.dispatcher_deploy:
            self.sonar = 'EXEMPT'
            self.sonar_date = 'N/A'
            self.autorollback = 'EXEMPT'
            self.autorollback_date = 'N/A'
            self.autorollback_enabled = False
            self.regression = 'EXEMPT'
            self.regression_date = 'N/A'
            self.regression_pass = 'N/A'
            self.regression_enabled = False
            self.ams = 'EXEMPT'
            self.skip_critical = True
            self.skip_smoke = True
            return            
        regression_quality_props = json.loads(os.getenv('REGRESSION_QUALITY_PROPS', '{}'))
        exception_status = yaml.safe_load(os.getenv('EXCEPTION_STATUS', '{}'))
        expiration_status = yaml.safe_load(os.getenv('EXPIRATION_STATUS', '{}'))
        critical_pre = os.getenv('CRITICAL_PRE')

        autorollback_result = 'N/A' if exception_status.get('auto_rollback', True) else 'EXEMPT'
        logger.info(f'Autorollback result: {autorollback_result}')
        logger.info(f'Exception status: {exception_status}')
        rollback_enabled = False if any([
            autorollback_result == 'EXEMPT',
            os.getenv('AUTO_DISABLE') == 'true',
            self.context.deploy_package.get('name').endswith('-config')
        ]) else True
        regression_date = expiration_status.get('regression_quality_gate', 'N/A').split(' ')[0]
        sonar_result = artifact_props.get('SONAR_QUALITY_GATE', ['NOT_FOUND'])[0] if exception_status.get('sonar', True) else 'EXEMPT'
        ams_result = artifact_props.get('AMS_CODE_QUALITY', ['N/A'])[0]
        sonar_date = expiration_status.get('sonar', 'N/A')
        regression_result = regression_quality_props.get('threshold-result', 'FAIL') if exception_status.get('regression_quality_gate', True) else 'EXEMPT'
        critical_passed, smoke_passed = self._set_smoke_pass(artifact_props, self.context.env, self.context.operation)

        self.sonar = sonar_result
        self.sonar_date = sonar_date
        self.autorollback = autorollback_result
        self.autorollback_date = expiration_status.get('auto_rollback', 'N/A')
        self.autorollback_enabled = rollback_enabled
        self.regression = regression_result
        self.regression_date = regression_date
        self.regression_pass = regression_quality_props.get('threshold-result', 'N/A')
        self.regression_enabled = regression_date != 'N/A'
        self.ams = ams_result
        self.skip_critical = critical_passed
        self.skip_smoke = smoke_passed
        self.sre_slo_id = artifact_props.get('SRE_SLO_ID', ['N/A'])[0]
        self.synthetic_id = artifact_props.get('SYNTHETIC_ID', ['N/A'])[0]
        self.nexus_id = artifact_props.get('NEXUS_ID', [''])[0]
        self.checkmarx_id = artifact_props.get('CHECKMARX_ID', [''])[0]
        self.branch = artifact_props.get('GIT_BRANCH', [''])[0]
        self.critical_pre = yaml.safe_load(critical_pre).get('jobs_passed') if critical_pre else None
        self.core_name = artifact_props.get('PROJECT_CORE_NAME', [None])[0]
        if self.context.manifest_deploy:
            self._check_quality()

    def _set_smoke_pass(self, artifact_props, deploy_env, deploy_operation):
        """set smoke props for environment manifest flow - if smoke has already passed it will be skipped on subsequent runs"""
        critical_prop = artifact_props.get('CRITICAL_TEST') if artifact_props.get('CRITICAL_TEST') else []
        smoke_prop = artifact_props.get('SMOKE') if artifact_props.get('SMOKE') else []
        critical_pass = False
        smoke_pass = False
        for critical_env in critical_prop:
            critical_env_prop = critical_env.split('~')
            if critical_env_prop[0] == deploy_env and critical_env_prop[1] == 'pass':
                logger.info(f'Artifact already passed critical tests in {deploy_env}')
                critical_pass = True
                break
        if re.match(r'(promote-to-){1}(stage|preprod){1}', str(deploy_operation)): # skip post-deploy critical tests for higher environments
            critical_pass = True
        for smoke_env in smoke_prop:
            smoke_env_prop = smoke_env.split('~')
            if smoke_env_prop[0] == deploy_env and re.match('success|pass', smoke_env_prop[1].lower()):
                logger.info(f'Artifact already passed smoke tests in {deploy_env}')
                smoke_pass = True
                break
        return critical_pass, smoke_pass
    
    def _check_quality(self):
        """Check if artifact failed quality check - if so it will be removed from deployment."""
        try:
            if self.context.manifest_deploy:
                quality_fail = False
                for x in [self.sonar, self.regression, self.ams]:
                    if re.match(r'OK|SKIPPED|EXEMPT|PASS', str(x).upper()) or self.context.dispatcher_deploy:
                        continue
                    quality_fail = True
                    break
                self.quality_fail = quality_fail
            return self
        except Exception as e:
            logger.error(f"Error in check_quality: {e}")

@dataclass
class AutoDeploy:
    env_name: str = ''
    env_id: str = ''
    next_env: str = ''
    next_env_name: str = ''
    cd_deployed: list = field(default_factory=list)
    skip_deploy: bool = False
    last_lower_env: bool = False
    jira_id: str = ''
    sre_id: str = ''
    load_id: str = ''
    ada_id: str = ''
    crq_id: str = ''
    teams_channel: str = ''
    load_self_waived: bool = False
    branch: str = ''
    region: str = ''
    qtest_folder: str = ''
    regression: list = field(default_factory=list)
    arb_risk: bool = False
    arb_risk_comment: str = ''
    fix_version: str = ''
    backout_artifact: str = ''
    appsec_result: str = ''
    release_type: str = ''
    update_release: bool = False
    content: Optional[Dict[str, Any]] = field(default_factory=dict)
    jira_subtasks: Optional[Dict[str, Any]] = field(default_factory=dict)
    snow_details: Dict[str, Any] = field(default_factory=dict)
    context: DeployContext = field(default_factory=DeployContext, repr=False)

    def __post_init__(self):
        """
        Sets the auto-deploy environment configuration based on the provided artifact properties, deployment environment, 
        and ReleaseReadinessConfig.yaml (RRC) file. The function is the single point at which the RRC file is read.

        This function determines the deployment order, environment mappings, and other deployment-related configurations. 
        It supports both manifest and non-manifest deployments and updates the provided package deployment map with the 
        auto-deploy configuration.
        """
        try:
            deploy_env = self.context.env
            manifest_deploy = self.context.manifest_deploy
            env_name_list = ['HINT', 'REGIONAL', 'LOAD', 'PREPROD', 'STAGE', 'PROD'] if manifest_deploy else ['DEV', 'QA']
            env_list_mapping = yaml.safe_load(os.getenv('AEM_CD_ENVIRONMENT_MAPPING', '{}'))
            teams_channel = artifact_props.get('TEAMS_CHANNEL', [''])[0]
            cd_deployed = artifact_props.get('CONTINUOUS_DEPLOY', [])
            check_mappings = lambda map_env: yaml.safe_load(os.getenv('AEM_CHECK_ENV_MAP', '{}')).get(map_env, map_env)
            last_lower_env = False

            with open(f'{workspace}/ReleaseReadinessConfig.yaml', 'r+') as f:
                rrc_config = yaml.safe_load(f)
            jira_details = rrc_config.get('jiraDetails', {})
            environments = jira_details.get('environments', {})
            logger.info(f"Environments from RRC: {environments}")
            rrc_config_map_items = {k: (env_list_mapping.get(k.lower(), None) if isinstance(v, bool) else v.lower()) for k, v in environments.items() if v}
            logger.info(f"RRC config map items: {rrc_config_map_items}")
            rrc_deploy_env_map = {k: [check_mappings(env).strip() for env in v.split(',')] if v is not None else [] for k, v in rrc_config_map_items.items()}
            logger.info(f"RRC deploy environment map before removing environments disabled in automation.yml: {rrc_deploy_env_map}")
            load_self_waived = rrc_config.get('loadIntakeDetails', {}).get('loadSelfWaived', False)
            rrc_deploy_env_map = {k: v for k, v in rrc_deploy_env_map.items() if k.lower() in env_list_mapping or k.lower() in ['dev', 'qa']}
            logger.info(f"RRC deploy environment map after removing environments disabled in automation.yml: {rrc_deploy_env_map}")
            if environments.get('PREPROD'):
                rrc_deploy_env_map.update({
                    'STAGE': [env_list_mapping.get('stage')],
                    'PROD': [env_list_mapping.get('prod')]
                    })
                logger.info(f"PREPROD enabled in RRC. Adding STAGE and PROD to RRC deploy env map: {rrc_deploy_env_map}")
            cd_envs_not_deployed = {k: [env for env in v if env not in cd_deployed] for k, v in rrc_deploy_env_map.items()}
            if manifest_deploy:
                cd_envs_not_deployed = {k: v for k, v in cd_envs_not_deployed.items() if k.upper() in env_name_list}
            skip_deploy = deploy_env.lower() not in [y.lower() for x in cd_envs_not_deployed.values() for y in x]
            env_name = next((k.upper() for k, v in rrc_deploy_env_map.items() if deploy_env in v), '')
            env_names = [x for x in cd_envs_not_deployed.keys() if x in env_name_list]

            if deploy_env in cd_envs_not_deployed.get(env_name, []):
                last_lower_env = deploy_env == cd_envs_not_deployed[env_names[-1]][-1] if cd_envs_not_deployed[env_names[-1]] else True
                keys_to_remove = list(cd_envs_not_deployed.keys())[:list(cd_envs_not_deployed.keys()).index(env_name)]
                for key in keys_to_remove:
                    del cd_envs_not_deployed[key]
                if deploy_env == cd_envs_not_deployed[env_name][-1]:
                    del cd_envs_not_deployed[env_name]
                else:
                    cd_envs_not_deployed[env_name].remove(deploy_env)
            elif not manifest_deploy:
                last_lower_env = True

            logger.info(f'\nDeploy environment: {deploy_env}\nCD environments not deployed: {cd_envs_not_deployed}')
            next_env, next_env_name, env_id = self._get_next_env(cd_envs_not_deployed, ('' if skip_deploy else env_name))

            # Set content package details if content change is detected
            content = rrc_config.get('content', {})
            if content.get('contentChange'):
                details = ''.join(content.get('contentDetails', []))
                content_hash = hashlib.sha256(details.encode('utf-8')).hexdigest()
                content['content_id'] = f"{self.context.deploy_package.get('name')}.content"
                content['content_version'] = content_hash[:10]

            self.env_name=env_name
            self.env_id=env_id
            self.next_env=next_env
            self.next_env_name=next_env_name
            self.cd_deployed=cd_deployed
            self.skip_deploy=skip_deploy
            self.last_lower_env=last_lower_env
            self.teams_channel=teams_channel
            self.load_self_waived=load_self_waived
            self.fix_version = jira_details.get('fixVersion')
            self.backout_artifact = rrc_config.get('backoutArtifactVersion', False)
            if not self.fix_version:
                raise ValueError("Fix version is missing in RRC. Please check the ReleaseReadinessConfig.yaml file and add valid fixVersion before proceeding.")
            self.release_type = rrc_config.get('releaseType', 'general')
            self.branch=artifact_props.get('GIT_BRANCH', ['master'])[0]
            self.content = content
            self.region=rrc_config.get('snowDetails', {}).get('impacted_region', 'N/A')
            self._set_regression_keys(rrc_config)
        except (StopIteration, IndexError, FileNotFoundError, RuntimeError) as e:
            raise RuntimeError(f'Error setting auto deploy map: {e}')

    def _get_next_env(self, cd_envs_not_deployed, env_name):
        """
        Determines the next environment to deploy to, its name, and the corresponding JIRA environment ID.
        Environments may be CSV so next environment name may be the same.
        """
        try:
            env_jira_mappings = yaml.safe_load(os.getenv('AEM_CD_JIRA_MAPPINGS', '{}'))
            next_env = next((v[0] for v in cd_envs_not_deployed.values() if v), '')
            next_env_name = next((k.upper() for k, v in cd_envs_not_deployed.items() if next_env in v), '')
            not_deployed_keys = list(cd_envs_not_deployed.keys())
            if next_env_name and next_env_name != 'DEV':
                prev_key_index = not_deployed_keys.index(next_env_name) - 1
                default_key = env_jira_mappings.get(not_deployed_keys[prev_key_index], '221') if prev_key_index >= 0 else '221'
            else:
                default_key = '221'
            if next_env:
                env_id = env_jira_mappings.get(env_name, default_key)
            else:
                env_id = env_jira_mappings.get('DONE', default_key)
            return next_env, next_env_name, env_id
        except (KeyError, IndexError, Exception) as e:
            logger.error(f"Error determining next environment: {e}")
            raise RuntimeError(f"Failed to determine next environment: {e}")
        
    def _set_regression_keys(self, rrc_config):
        """Get regression and dod environments from the RRC file and set them in the auto_deploy map, with error handling."""
        try:
            jira_details = rrc_config['jiraDetails']
            auto_deploy_envs = jira_details['environments']
            regression_envs = jira_details.get('regression',[]) # TODO removing regression & dod envs until we have a better way to handle them
            self.qtest_folder = rrc_config.get('qTestFolder') or ''
            self.arb_risk = rrc_config.get('arbRisk', False)
            self.arb_risk_comment = rrc_config.get('arbRiskComment', '')
            check_mappings = lambda map_env: yaml.safe_load(os.getenv('AEM_CHECK_ENV_MAP', '{}')).get(map_env, map_env)
            if regression_envs:
                dod_envs = set([x.lower() for x in jira_details.get('dod',[])]).intersection([x.lower() for x in regression_envs])
                self.regression = [check_mappings(auto_deploy_envs[k]).lower() for k in auto_deploy_envs.keys() if k.lower() in [x.lower() for x in regression_envs]]
                if dod_envs:
                    self.dod_envs = [check_mappings(auto_deploy_envs[k]).lower() for k in auto_deploy_envs.keys() if k.lower() in [x.lower() for x in dod_envs]]
            rrc_snow_details = rrc_config.get('snowDetails', {})
            # Add openEnrollmentRiskAnalysis section as a key if present
            if rrc_config.get('openEnrollmentRiskAnalysis', {}):
                rrc_snow_details['openEnrollmentRiskAnalysis'] = rrc_config.get('openEnrollmentRiskAnalysis')
            rrc_snow_release_date = rrc_snow_details.get('ScheduledDate')
            self._validate_release_date(rrc_snow_release_date)
            self.snow_details = rrc_snow_details
        except (KeyError, AttributeError, Exception) as e:
            logger.error(f"Error in get_auto_regression_keys: {e}")
            raise RuntimeError(f"Failed to get auto regression keys: {e}")

    def _validate_release_date(self, rrc_snow_release_date):
        if rrc_snow_release_date:
            try:
                pst = pytz.timezone('US/Pacific')
                release_date = datetime.strptime(rrc_snow_release_date, '%m/%d/%Y')
                release_date = pst.localize(release_date)
                if release_date.date() < datetime.now(pst).date():
                    raise ValueError(f"Release date {rrc_snow_release_date} is not after the current date.")
            except ValueError as e:
                raise ValueError(f"Invalid date format or value for ScheduledDate: {rrc_snow_release_date}: {e} Date should be in the future and using format: MM/DD/YYYY.")
        else:
            logger.info("No ScheduledDate provided in the RRC file.") # TODO should we throw an error if no date is provided?

    def to_json(self) -> dict:
        """Return a JSON-serializable representation of the AutoDeploy instance with error handling."""
        try:
            def serialize(obj):
                if hasattr(obj, "__dict__"):
                    return {k: serialize(v) for k, v in obj.__dict__.items() if k != "context"}
                elif isinstance(obj, dict):
                    return {k: serialize(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [serialize(i) for i in obj]
                else:
                    return obj
            return serialize(self)
        except Exception as e:
            logger.error(f"Error serializing AutoDeploy to JSON: {e}")
            raise RuntimeError(f"Failed to serialize AutoDeploy: {e}")

@dataclass
class DeploymentData:
    name: str = ''
    env: str = ''
    manifest_deploy: bool = False
    dispatcher_deploy: bool = False
    operation: str = "N/A"
    version: str = "N/A"
    quality: Optional[QualityProperties] = None
    auto_deploy: Optional[AutoDeploy] = None
    deploy: dict = field(default_factory=lambda: dict(deploy_status='SUCCESS', rollback=False))
    post_deploy: dict = field(default_factory=dict)
    deploy_package: Optional[dict] = None

    def __post_init__(self):
        """Initalize deploy package map (primary + any secondary artifacts) and rollback properties."""
        try:
            self.name = self.deploy_package.get('name', self.name) if self.deploy_package else self.name
            self.dispatcher_deploy = self.name == 'ams-configs'
            deploy_module = self.deploy_package.get('module_values_deploy', {})
            self.version = deploy_module.get('artifact_version', 'N/A') if self.deploy_package else 'N/A'
        except Exception as e:
            logger.error(f"Error initializing DeploymentData: {e}")
            raise RuntimeError(f"Failed to initialize DeploymentData: {e}")

    def create_map(self):
        """Create the deployment data map with quality and auto_deploy properties."""
        try:
            context = DeployContext(
                env=self.env,
                operation=self.operation,
                manifest_deploy=self.manifest_deploy,
                dispatcher_deploy=self.dispatcher_deploy,
                deploy_package=self.deploy_package
            )
            if self.dispatcher_deploy:
                self.quality = QualityProperties(context=context)
                self._set_dispatcher_map()
            else:
                if not artifact_props:
                    raise RuntimeError('Artifact properties not found.')
                self.quality = QualityProperties(context=context)
            if self.deploy_package.get('cd_deploy'):
                self.auto_deploy = AutoDeploy(context=context)
                if self.auto_deploy.env_name == 'DEV':
                    self.quality.autorollback_enabled = False
                self._update_cd_map()
            return self
        except Exception as e:
            logger.error(f"Error creating deployment data map: {e}")
            raise RuntimeError(f"Failed to create deployment data map: {e}")

    def add_rollback(self):
        try:
            last_deployed = yaml.safe_load(os.getenv('LAST_DEPLOYED') or '{}')
            rollback_result = bool(last_deployed)
            self.deploy_package['module_values_rollback'] = dict(
                artifact_id=last_deployed.get('app_id'),
                artifact_version=last_deployed.get('app_version')
            ) if rollback_result else {}
            primary_artifact = self.deploy_package.get('module_values_deploy', {}).get('artifact_id')
            secondary_artifacts = [package.split(':')[0] for package in artifact_props.get('SECONDARY_ARTIFACTS') or []]
            self.deploy_package['primary'] = primary_artifact
            self.deploy_package['deploy_artifacts'] = [primary_artifact] + secondary_artifacts
            self.deploy_package['path'] = {primary_artifact: last_deployed.get('app_path', '')}
            return self
        except Exception as e:
            logger.error(f"Error initializing DeploymentData: {e}")
            raise RuntimeError(f"Failed to initialize DeploymentData: {e}")
        
    def _update_cd_map(self):
        try:
            appsec_result = yaml.safe_load(os.getenv('APPSEC_RESULT') or '{}')
            release_status = yaml.safe_load(os.getenv('RELEASE_RECORD') or '{}')
            release_record = release_status.get('release', {})
            subtask_record = release_status.get('subtasks', {})
            logger.info(f"Release record: {release_record}")
            logger.info(f"Subtask record: {subtask_record}")
            jira_subtasks = {} # Existing JIRA subtasks status
            jira_subtask_updates = {} # JIRA subtasks updates to be applied

            auto_deploy = self.auto_deploy
            # Set IDs from release_record if present
            jira_id = release_record.get('jira_id', '') if release_record else ''
            auto_deploy.jira_id = jira_id
            auto_deploy.crq_id = release_record.get('crq_id', '') if release_record else ''
            auto_deploy.sre_id = release_record.get('sre_id', '') if release_record else ''
            auto_deploy.load_id = release_record.get('load_id', '') if release_record else ''
            auto_deploy.ada_id = release_record.get('ada_id', '') if release_record else ''
            if jira_id:
                os.system(f'echo "jira-id={jira_id}" >> $GITHUB_OUTPUT')

            # Compare JIRA release date with ServiceNow release date to update KP.ORG release if needed
            update_release = False
            snow_details = auto_deploy.snow_details
            release_date = snow_details.get('ScheduledDate') if snow_details else None
            jira_release_date = release_record.get('release_date') if release_record else None
            if release_date and jira_release_date:
                dt_jira = datetime.strptime(jira_release_date, "%b.%d.%Y")
                dt_release = datetime.strptime(release_date, "%m/%d/%Y")
                if dt_jira.date() != dt_release.date():
                    logger.warning(
                        f"Mismatch in release dates: JIRA release date is {dt_jira}, "
                        f"but ServiceNow release date is {dt_release}."
                    )
                    update_release = True

            # Update JIRA subtasks with results from subtask_record
            if subtask_record:
                for subtask in subtask_record:
                    jira_subtasks[subtask.get('st_type')] = {'st_status': subtask.get('st_status', False)}

            # Compare JIRA release version with auto-deploy package version to update the version if needed
            release_version = release_record.get('app_version', '') if release_record else ''
            package_version = self.deploy_package.get('module_values_deploy', {}).get('artifact_version', '')
            if release_version and release_version != package_version:
                logger.info(f"Updating version from {release_version} to {package_version}.")
                update_release = True
                jira_subtask_updates['regression_result'] = {'st_status': False}
                jira_subtask_updates['dod_result'] = {'st_status': False}

            if update_release:
                auto_deploy.sre_id = '' # reset SRE ID if release or version are updated

            # Check if content details match the release record to determine need to rebuild content package
            if self.auto_deploy.content and release_record.get('secondary_data') is not None:
                jira_subtask_updates['content_result'] = {'title': 'Content package', 'st_status': True, 'comment': 'Content package created.'}
                if release_record.get('secondary_data', {}).get('content_version') == self.auto_deploy.content.get('content_version'):
                    logger.info("Content details match the release record. Will not rebuild content package.")
                    del jira_subtask_updates['content_result']
                    auto_deploy.content = False
                else:
                    logger.info("Content details do not match the release record. Will rebuild content package.")
                    jira_subtask_updates['content_result']['comment'] = 'Content package updated.'
                    update_release = True

            # Update deployment data with subtask results
            quality = self.quality
            if appsec_result.get('result') == 'FAILED':
                quality.appsec_fail = appsec_result.get('jira_comment', '')
            elif appsec_result: # repo flow
                if appsec_result.get('result') == 'PASSED':
                    jira_subtask_updates['appsec_result'] = {'st_status': True, 'comment': appsec_result.get('jira_comment', '')}
                    auto_deploy.appsec_result = 'Exception-TRO' if 'exception-tro' in appsec_result.get('jira_comment', '').lower() else 'Approved'
                if self.auto_deploy.load_self_waived:
                    jira_subtask_updates['load_result'] = {'st_status': True, 'comment': 'Load ticket created.'}

            auto_deploy.update_release = update_release
            auto_deploy.jira_subtasks = jira_subtasks
            quality.jira_subtask_updates = jira_subtask_updates
            self.quality = quality
            self.auto_deploy = auto_deploy
            return self
        except (KeyError, Exception) as e:
            logger.error(f"Error updating deployment data: {e}")        

    def _set_dispatcher_map(self):
        """set deploy package map for ams dispatcher"""
        try:
            deploy_result = 'success' # default value
            msg = f"Dispatcher deploy result {deploy_result} for AMS configs version {self.deploy_package.get('module_values_deploy').get('artifact_version')}"
            self.post_deploy['comments'] = msg
            self.post_deploy['overall_status'] = deploy_result
        except (KeyError, TypeError, Exception) as e:
            logger.error(f"Error setting dispatcher map: {e}")
            raise RuntimeError(f"Failed to set dispatcher map: {e}")

    def to_json(self) -> dict:
        """Return a JSON-serializable representation of the DeploymentData instance with error handling."""
        try:
            def serialize(obj):
                if hasattr(obj, "__dict__"):
                    return {k: serialize(v) for k, v in obj.__dict__.items() if k != "context"}
                elif isinstance(obj, dict):
                    return {k: serialize(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [serialize(i) for i in obj]
                else:
                    return obj
            return serialize(self)
        except Exception as e:
            logger.error(f"Error serializing DeploymentData to JSON: {e}")
            raise RuntimeError(f"Failed to serialize DeploymentData: {e}")

    def to_file(self):
        """Write the DeploymentData object as a JSON file with error handling."""
        try:
            file_path = os.path.join(workspace, 'package_deploy_map.json')
            with open(file_path, 'w') as f:
                json.dump(self.to_json(), f, indent=2)
        except Exception as e:
            logger.error(f"Error writing DeploymentData to file: {e}")
            raise RuntimeError(f"Failed to write DeploymentData to file: {e}")            
