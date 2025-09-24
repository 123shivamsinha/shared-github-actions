import subprocess
import sys
import os
import re
import yaml
from kpghalogger import KpghaLogger
logger = KpghaLogger()

workspace = os.getenv('GITHUB_WORKSPACE')
action_path = os.getenv('GITHUB_ACTION_PATH')

def main():
    operation = os.getenv('OPERATION')
    config_map = yaml.safe_load(sys.argv[1])
    if operation == 'set-vars':
        set_vars(config_map)
    elif operation == 'reports':
        generate_test_reports(config_map)
    elif operation == 'remove-artifacts':
        remove_artifacts()


def set_vars(config_map):
    '''set build vars runtime-version, args-build, args-test'''
    build_type = config_map.get('app_props').get('build_type')
    runtime_version = config_map.get('runtime_version')
    java_version = config_map.get('java_version')
    node_version = config_map.get('node_version')
    if os.getenv('GHA_ORG') == 'ENTERPRISE':
       delete_yarn_lock_flag = config_map.get('build_group', {}).get('delete-yarn-lock-flag', 'true')
       logger.info(f"delete yarn lock flag: {delete_yarn_lock_flag}")    
    if re.match('npm|dotnet|pip', build_type) and java_version: # set java runtime for test suite
        set_runtime_version(java_version)
    elif runtime_version:
        set_runtime_version(runtime_version)
    else:
        logger.info('Using default runtimes.')
    os.system(f"echo 'runtime-version={runtime_version}' >> $GITHUB_OUTPUT")
    if node_version:
        os.system(f"echo 'node-version={node_version}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'args-build={config_map.get('args_build')}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'args-test={config_map.get('args_test')}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'test-flag-enabled={config_map.get('test_flag_enabled')}' >> $GITHUB_OUTPUT")
    if os.getenv('GHA_ORG') == 'ENTERPRISE':
       os.system(f"echo 'delete-yarn-lock-flag={delete_yarn_lock_flag}' >> $GITHUB_OUTPUT")


def generate_test_reports(config_map):
    '''generate code coverage reports'''
    try:
        args_test = config_map['args_test']
        if args_test:
            run_test_cmd = f"{args_test}"
            logger.info(f'Generating test report using {run_test_cmd}')
            try:
                subprocess.run(run_test_cmd, shell=True, check=True, timeout=3600)
            except (subprocess.TimeoutExpired, RuntimeError) as e:
                raise RuntimeError(f'Error creating test reports: {e}') from e
        build_group = config_map.get('build_group')
        module_name = build_group.get('module-name') if build_group.get('module-name') else ''
        jacoco = build_group.get('jacoco')
        cobertura = build_group.get('cobertura')
        test_report_xml = build_group.get('test-result-xml')
        if jacoco:
            report_present = subprocess.check_output([f"find {workspace}/{module_name} -type d -name jacoco"], shell=True, text=True).strip()
            if report_present:
                report_path = '**/target/site/jacoco/**'
                logger.info(f"Jacoco report path {report_path}")
                os.system(f"echo 'jacoco-report-path={report_path}' >> $GITHUB_OUTPUT")
            else:
                logger.warning(logger.format_msg('GHA_BUILD_MAVEN_BIZ_3_2001', 'No Jacoco reports were produced', {'detailMessage': f'Jacoco execution did not produce any reports', 'metrics': {'status': 'failure'}}))
        if cobertura:
            logger.info('Cobertura enabled')
        if test_report_xml:
            test_report_path = f"{workspace}/{test_report_xml}"
            logger.info(f"Test report path {test_report_path}")
            os.system(f"echo 'test-report-path={test_report_path}' >> $GITHUB_OUTPUT")
        
        try:
            html_report_dir = build_group.get('html-reports').get('pipeline-coverage-report').get('report-dir')
        except AttributeError:
            html_report_dir = None
            logger.error('No HTML report found.')
        if html_report_dir:
            try:
                html_report_path = subprocess.check_output([f"find {workspace}/{module_name} -type d -name {html_report_dir}"], shell=True, text=True).strip()
                if html_report_path:
                    logger.info(f"HTML report path {html_report_path}")
                    os.system(f"echo 'html-report-path={html_report_path}' >> $GITHUB_OUTPUT")
            except RuntimeError: logger.warning(logger.format_msg('GHA_BUILD_MAVEN_BIZ_3_2002', 'No HTML reports were produced', {'detailMessage': f'Test execution did not produce any HTML reports', 'metrics': {'status': 'failure'}}))
    except RuntimeError as e:
        raise RuntimeError(f'Error running build tests: {e}.')
        logger.error(logger.format_msg('GHA_BUILD_MAVEN_BIZ_4_2001', 'Build test error', {'detailMessage': f'Error running build tests: {e}', 'metrics': {'status': 'failure'}}))


def set_runtime_version(runtime_version):
    if runtime_version.startswith("17"):
        jdk_path = f'/usr/lib/jvm/jdk-{runtime_version}'
    elif runtime_version.startswith("21"):
        jdk_path = '/etc/alternatives/java_sdk_21'
    elif runtime_version.startswith("23"):
        jdk_path = '/etc/alternatives/java_sdk_23'
    elif runtime_version in ["1.8", "8"]:
        jdk_path = '/usr/lib/jvm/jdk-8'
    else:
        jdk_path = '/usr/lib/jvm/jdk-11'  # default fallback

    command = (
        f'export JAVA_HOME={jdk_path} && '
        f'sudo update-alternatives --set java $(readlink {jdk_path})/bin/java && '
        f'java -version && mvn --version'
    )
    subprocess.run(command, shell=True)

    env_command = f'echo "JAVA_HOME={jdk_path}" >> $GITHUB_ENV'
    subprocess.run([env_command], shell=True, text=True)


def remove_artifacts():
    '''
    method removes liberty server artifact used in local builds
    '''
    try:
        remove_artifacts = subprocess.run(f'rm -r {workspace}/**/LibertyServer', shell=True)
    except RuntimeError:
        logger.info(remove_artifacts.returncode)


if __name__ == '__main__':
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "start"}}))
    main()
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))