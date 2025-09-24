import subprocess
import sys
import yaml
import os
import re
from kpghalogger import KpghaLogger
logger = KpghaLogger()

workspace = os.getenv('GITHUB_WORKSPACE')
action_path = os.getenv('GITHUB_ACTION_PATH')

def main():
    operation = os.getenv('OPERATION')
    config_map = yaml.safe_load(sys.argv[1]) if len(sys.argv) > 1 else {}
    if operation == 'set-vars':
        set_vars(config_map)
    elif operation == 'test-report':
        test_report()
    elif operation == 'remove-artifacts':
        remove_artifacts()
    elif operation == 'publish':
        publish()

def set_vars(config_map):
    '''
    set build vars runtime-version, args-build, args-test
    '''
    build_type = config_map.get('app_props').get('build_type')
    runtime_version = config_map.get('runtime_version')
    pip_version = config_map.get('pip_version')
    os.system(f"echo 'runtime-version={runtime_version}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'pip-version={pip_version}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'args-build={config_map.get('args_build')}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'args-test={config_map.get('args_test')}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'test-flag-enabled={config_map.get('test_flag_enabled')}' >> $GITHUB_OUTPUT")

def test_report():
    '''
    generate test coverage report and create path for it
    use html report for test coverage report artifact in GHA Summary
    use xml report to create a compatible one with sonar scan coverage
    '''
    try:
        report_path = f'{workspace}/htmlcov/index.html'
        logger.info(f"report path {report_path}")
        os.system(f"echo 'report-path={report_path}' >> $GITHUB_OUTPUT")
    except RuntimeError as e:
        raise RuntimeError(f'Error running build tests: {e}.')

def remove_artifacts():
    '''
    method removes excess artifacts
    '''
    try:
        remove_artifacts = subprocess.run(f'rm -r {workspace}/**/*.tar', shell=True)
    except RuntimeError:
        logger.error(f'error code while removing artifact: {remove_artifacts.returncode}')


def publish():
    '''
    method to publish artifacts
    '''
    try:
        os.chdir(f'{workspace}/dist')
        for x in os.listdir():
            y = re.sub(r'_', '-', x)
            os.rename(x, y)
            logger.info(f'Publishing artifact {y}')
    except RuntimeError:
        logger.error(f'Error code while publish: {publish.returncode}')


if __name__ == '__main__':
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "start"}}))
    main()
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))
