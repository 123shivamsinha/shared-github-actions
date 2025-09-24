import subprocess
import sys
import os
import yaml
from kpghalogger import KpghaLogger
logger = KpghaLogger()
workspace = os.getenv('GITHUB_WORKSPACE')

def main():
    operation = sys.argv[1]
    config_map = yaml.safe_load(sys.argv[2])
    if operation == 'set-vars':
        set_vars(config_map)
    elif operation == 'generate-report':
        generate_test_reports(config_map)


def generate_test_reports(build_var_map):
    args_test = build_var_map.get('args_test')
    source_directory = build_var_map.get('build_group').get('source-directory','')
    if args_test:
        logger.info(f'Generating test report using {args_test}')
        try:
            os.chdir(f"{workspace}/{source_directory}")
            subprocess.run(f'export LOG_LEVEL=ERROR && {args_test}', shell=True, check=True, timeout=3600)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError) as e:
            logger.error(logger.format_msg('GHA_BUILD_NPM_BIZ_4_2001', 'Build test error', {'detailMessage': f'Error running build tests: {e}', 'metrics': {'status': 'failure'}}))
            sys.exit(1)  # Mark the build as failed
    build_group = build_var_map.get('build_group')
    lcov_report_path = build_group.get('js-lcov-report-path')
    cobertura = build_group.get('cobertura')
    cobertura_report_path = None
    if cobertura:
        subprocess.run(f'python -m pycobertura show --format html --output coverage/cobertura-coverage.html coverage/cobertura-coverage.xml', shell=True)        
        cobertura_report_path = f"{workspace}/coverage/cobertura-coverage.html"

    try:
        html_report_dir = build_group.get('html-reports',{}).get('pipeline-coverage-report',{}).get('report-dir')
    except AttributeError as e:
        html_report_dir = None
        logger.error(logger.format_msg('GHA_BUILD_NPM_BIZ_4_2002', 'No HTML reports found', {'detailMessage': f'No HTML report found: {e}', 'metrics': {'status': 'failure'}}))

    if lcov_report_path:
        lcov_dir = build_var_map.get('build_group').get('source-directory','')
        lcov_html_report_path = f"{workspace}/{lcov_dir}/coverage/lcov-report"
        logger.info(f"Lcov report path {lcov_report_path}")
        os.system(f"echo 'lcov-report-path={workspace}/{lcov_dir}/{lcov_report_path}' >> $GITHUB_OUTPUT")
        logger.info(f"Lcov html report path {lcov_html_report_path}")
        os.system(f"echo 'lcov-html-report-path={lcov_html_report_path}' >> $GITHUB_OUTPUT")

    if cobertura_report_path:
        logger.info(f"cobertura report path {cobertura_report_path}")
        os.system(f"echo 'cobertura-report-path={cobertura_report_path}' >> $GITHUB_OUTPUT")

    if html_report_dir:
        try:
            html_report_path = subprocess.check_output(
                f"find {workspace} -maxdepth 1 -type d -name '{html_report_dir}'",
                shell=True, text=True
            ).strip()
            if html_report_path:
                logger.info(f"HTML report path {html_report_path}")
                os.system(f"echo 'html-report-path={html_report_path}' >> $GITHUB_OUTPUT")
        except Exception as e:
            logger.error(logger.format_msg('GHA_BUILD_NPM_BIZ_4_2003', 'No HTML reports were produced', {'detailMessage': f'Test execution did not produce any HTML reports: {e}', 'metrics': {'status': 'failure'}}))


def set_vars(config_map):
    runtime_version = config_map.get('runtime_version')
    if runtime_version:
        os.system(f"echo 'runtime-version={runtime_version}' >> $GITHUB_OUTPUT")
    test_flag_enabled = True if all([config_map.get('test_flag_enabled'), config_map.get('args_test')]) else False
    os.system(f"echo 'args-build={config_map['args_build']}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'args-test={config_map['args_test']}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'test-flag-enabled={test_flag_enabled}' >> $GITHUB_OUTPUT")
    if config_map['build_group'].get('build-tool','npm'):
       os.system(f"echo 'build-tool={config_map['build_group'].get('build-tool','npm')}' >> $GITHUB_OUTPUT")


if __name__ == '__main__':
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "start"}}))
    main()
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))
