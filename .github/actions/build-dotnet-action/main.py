import subprocess
import sys
import os
import yaml

from kpghalogger import KpghaLogger
logger = KpghaLogger()

workspace = os.getenv('GITHUB_WORKSPACE')
action_path = os.getenv('GITHUB_ACTION_PATH')

def main():
    operation = sys.argv[1]
    config_map = yaml.safe_load(sys.argv[2])
    if operation == 'set-vars':
        set_vars(config_map)
    if operation == 'test-report':
        test_report()

def set_vars(config_map):
    '''
    set build vars runtime-version, args-build, args-test
    '''
    app_name=config_map.get('app_props').get('app_name')
    runtime_version = config_map.get('sdk_version')
    app_version = config_map.get('app_props').get('product_version')
    os.system(f"echo 'app-name={app_name}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'app-version={app_version}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'runtime-version={runtime_version}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'args-build={config_map.get('args_build')}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'configuration={config_map.get('configuration')}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'args-test={config_map.get('args_test')}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'test-flag-enabled={config_map.get('test_flag_enabled')}' >> $GITHUB_OUTPUT")

def test_report():
    '''
    generate test coverage report compatible with sonar scan coverage
    '''
    try:
        report_path = f'{workspace}/*/TestResults/*.xml'
        try:
            logger.info(f"report path {report_path}")
            os.system(f"echo 'report-path={report_path}' >> $GITHUB_OUTPUT")
        except (subprocess.TimeoutExpired, RuntimeError) as e:
            raise RuntimeError(f'Error producing any report: {e}') from e
    except RuntimeError as e:
        logger.error(logger.format_msg('GHA_BUILD_DOTNET_BIZ_4_2001', 'Build test error', {'detailMessage': f'Error running build tests: {e}', 'metrics': {'status': 'failure'}}))
        raise RuntimeError(f'Error running build tests: {e}.')
        
if __name__ == '__main__':
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "start"}}))
    main()
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))