import subprocess
import os
import re
import time
import yaml
import json
import pytz
from datetime import datetime
from kpghalogger import KpghaLogger
logger = KpghaLogger()

github_url = os.getenv('GITHUB_SERVER_URL')
workspace = os.getenv('GITHUB_WORKSPACE')
deploy_env = os.getenv('DEPLOY_ENV')
test_type = os.getenv('TEST_TYPE')
artifact_version = os.getenv('ARTIFACT_VERSION')
COLOR_RED = "\u001b[31m"


def update_secrets():
    secret_names = os.getenv('SECRET_NAMES').split('::')
    secret_values = os.getenv('SECRET_VALUES').split('::')
    
    if len(secret_names) != len(secret_values): raise Exception(f'There must be equal number of secrets and values.')

    # set secrets
    secret_map = dict(zip(secret_names, secret_values))
    for k,v in secret_map.items():
        secret_name = k.strip().replace('-','_').upper()
        secret_value = v.strip().replace(' ','')
        gh_add_secret = subprocess.run(f"gh secret set {secret_name} --body '{secret_value}'", shell=True, capture_output=True)
        if gh_add_secret.returncode != 0:
            logger.info(gh_add_secret.stderr.decode())
        
    # list secrets
    gh_login = subprocess.run('gh secret list', shell=True, capture_output=True)
    if gh_login.returncode != 0:
        logger.info(gh_login.stderr.decode())
    else: logger.info(gh_login.stdout.decode())


def check_secrets():
    secret_names = os.getenv('SECRET_NAMES').split('::')
    secret_values = os.getenv('SECRET_VALUES').split('::')
    if len(secret_names) != len(secret_values):
        raise Exception(f'{COLOR_RED}There must be equal number of secrets and values.')
    else:
        set_repo(os.getenv('GITHUB_REPOSITORY'), 'secrets')
    secret_env = {}
    accepted_pattern = r"^[a-zA-z0-9]+$"
    for x,y in zip(secret_names, secret_values):
        logger.info(f'Checking secret {x}...')
        os.system(f"echo '::add-mask::{y}' && echo '{x}={y}' >> $GITHUB_ENV")
    for name in secret_names:
        if not bool(re.match(accepted_pattern, name)):
            raise Exception(f"{COLOR_RED}Failed to add secret. Secret names can only contain alphanumeric characters ([a-z], [A-Z], [0-9]) or underscores (_). Spaces are not allowed. Must start with a letter ([a-z], [A-Z]) or underscores (_).")
        if not name.upper().startswith('AZ'):
            if re.search('NONPROD$|NON_PROD$', name.upper()):
                env = 'dev'
                secret_env['dev'] = True
            elif name.upper().endswith('PROD'):
                env = 'prod'
                secret_env['prod'] = True
                os.system(f"echo 'DEPLOY_ENV={env}' >> $GITHUB_ENV")
            else:
                raise Exception(f'{COLOR_RED}Secret name must start with AZ or end with PROD, NONPROD, or NON_PROD.')
            logger.info(f'Setting KP config check to {env} secret')
    os.system(f"echo 'env-name={json.dumps(secret_env)}' >> $GITHUB_OUTPUT")


def regression():
    watch_run = True if os.getenv('WATCH_RUN') == 'true' else False
    result_map = yaml.safe_load(os.getenv('RESULT_MAP', '{}'))
    qtest_folder = result_map.get('qtest_folder')
    dod_check = str(result_map.get('dod')).lower()
    repo_name = ""
    check_workflow("Regression", repo_name, watch_run, qtest_folder, dod_check)

def cross_browser():
    watch_run = True if os.getenv('WATCH_RUN') == 'true' else False
    qtest_release_cycle_id = os.getenv('QTEST_RELEASE_CYCLE_ID', '')
    repo_name = os.getenv('REPO', '')
    check_workflow("Cross Browser", repo_name, watch_run, qtest_release_cycle_id)


def check_workflow(job_type, repo_name="", watch_run=False, qtest_folder="", dod_check="", qtest_release_cycle_id=""):
    repo = repo_name or os.getenv('REPO')
    repo_branch = os.getenv('BRANCH')
    branch_name = f'--ref {repo_branch}' if repo_branch else ''
    repo_org = os.getenv('REPO_ORG')
    github_repo = f'{repo_org}/{repo}'
    job_status = 'FAILURE'
    logger.info(f'Check {job_type} condition for {github_repo}...')
    try:
        workflow_id = set_repo(github_repo, job_type, repo) # repo parameter added to accommodate call for extension
        if workflow_id:
            logger.info(f'{job_type} workflow {workflow_id} present in repo')
        else:
            logger.info(f'{job_type} not found in GHA for {repo}.')
            exit(0)
        
        if job_type == "Regression":
            gh_run_workflow = subprocess.run(f"gh workflow run {workflow_id} -F environment={deploy_env} -F dod-check={dod_check} -F dod-qtest-folder=\"{qtest_folder}\" {branch_name}", shell=True, capture_output=True)
        elif job_type == "Deployment Validation":
            gh_run_workflow = subprocess.run(f"gh workflow run {workflow_id} -F test-type={test_type} -F environment={deploy_env} -F test-artifact-version={artifact_version}", shell=True, capture_output=True)
        elif job_type == "Cross Browser":
            gh_run_workflow = subprocess.run(f"gh workflow run {workflow_id} -F environment={deploy_env} -F test-type='p1 + target' -F qtest-release-cycle-id={qtest_release_cycle_id} -F test-artifact-version={artifact_version}", shell=True, capture_output=True)
        else:
            # build pipeline extension
            gh_run_workflow = subprocess.run(f"gh workflow run {workflow_id} -F operation=build-pipeline-extension", shell=True, capture_output=True)
            subprocess.run(f'git remote remove {repo}', shell=True, capture_output=True)
        if gh_run_workflow.returncode != 0:
            logger.info(gh_run_workflow.stderr.decode())
            exit(0)
        time.sleep(3)

        # get run
        gh_run_list = subprocess.run(f"gh run list -w {workflow_id} | sed -n 1p", shell=True, capture_output=True)
        if gh_run_list.returncode != 0:
            logger.info(gh_run_list.stderr.decode())
        else:
            gh_run = re.split('\s+', gh_run_list.stdout.decode().strip().split('workflow_dispatch')[1].strip())[0]
            run_url = f'{github_url}/{github_repo}/actions/runs/{gh_run}'
            logger.info(f'GH run URL: {run_url}')
            os.system(f"echo 'test-url={run_url}' >> $GITHUB_OUTPUT")

        if ((watch_run and job_type == "Regression") or job_type == "Deployment Validation"):
            try:
                gh_run_watch = subprocess.Popen(['gh','run','watch',gh_run,'-i','20','--exit-status'], stdout=subprocess.PIPE)
                while gh_run_watch.stdout.readlines():
                    logger.info(f'Waiting for GHA {job_type} job at {github_url}/{github_repo}/actions/runs/{gh_run} ...')
                exit_status = gh_run_watch.wait()
                if exit_status == 0:
                    job_status = 'SUCCESS'
                else:
                    raise Exception("Watch run exception")
            except Exception as e:
                job_status = 'FAILURE'
            if job_status == 'SUCCESS':
                logger.info(f'Job passed at {run_url}')
            else:
                logger.info(f'Job failed at {run_url}')        
            os.system(f"echo 'test-result={job_status}' >> $GITHUB_OUTPUT")
            logger.info(f'{job_type} job result: {job_status}')

    except Exception as e:
        raise ValueError(f'Error in {job_type} workflow: {e}')


def extension_job():
    batch_repos = yaml.safe_load(os.getenv('REPO'))
    total_len = len(batch_repos)
    if isinstance(batch_repos, str):
        batch_repos = [ x.strip() for x in batch_repos.split(',') ]
    i = 0
    workflow_name = 'Build & Deploy'
    for repo in batch_repos:
        batch_repos.remove(repo)
        i += 1        
        try:
            check_workflow(workflow_name, repo)
        finally:
            logger.info(f'{i} of {total_len} extension jobs completed.')
            if i % 30 == 0:
                logger.info(f"Remaining repos:\n{','.join(batch_repos)}")
                time.sleep(300) # pause for 5 minutes before checking limits
                rate_limit()


def set_repo(github_repo, workflow, repo='newrepo'):
    # add repo
    gh_add_repo = subprocess.run(f'git init && git remote add {repo} {github_url}/{github_repo}', shell=True, capture_output=True)
    if gh_add_repo.returncode != 0:
        logger.info(gh_add_repo.stderr.decode())

    # login
    gh_login = subprocess.run('gh auth status', shell=True, capture_output=True)
    if gh_login.returncode != 0:
        logger.info(gh_login.stderr.decode())

    # set repo
    gh_set_repo = subprocess.run(f"gh repo set-default {github_repo}", shell=True, capture_output=True)
    if gh_set_repo.returncode != 0:
        logger.info(gh_set_repo.stderr.decode())

    # check workflows
    workflow_id = False
    if workflow == 'secrets': # only need to set repo context, not fetch workflows
        return
    gh_view_workflow = subprocess.run("gh workflow list", shell=True, capture_output=True)
    if gh_view_workflow.returncode != 0:
        logger.info(gh_view_workflow.stderr.decode())
    else:
        logger.info(f'\n{gh_view_workflow.stdout.decode()}')
        repo_workflows = gh_view_workflow.stdout.decode().split('\n')
        for repo_workflow in repo_workflows:
            if repo_workflow.split('active')[0].strip() == workflow:
                workflow_id = repo_workflow.split('active')[1].strip()
    return workflow_id
    

def rate_limit():
    try:
        git_api = subprocess.run('gh api rate_limit', shell=True, capture_output=True).stdout.decode().strip()
        prod_deploy = True if re.match('preprod|stage|prod|uat|dr|drn', deploy_env.split('-')[-1]) else False
        api_threshold = 15
        rate_limits = json.loads(git_api)
        logger.info(json.dumps(rate_limits))
        graphql_remaining = rate_limits.get('resources',{}).get('graphql',{}).get('remaining',200)
        logger.info(f'GraphQL rate limit remaining: {graphql_remaining}')
        if graphql_remaining < 50 and os.getenv('GITHUB_REPOSITORY') == 'CDO-KP-ORG/doet-gha-utilities':
            logger.error(f'GraphQL rate limit remaining ({graphql_remaining}) is < 50. Sleeping.')
            time.sleep(3600)
        api_rate = rate_limits.get('rate')
        api_remaining = api_rate.get('remaining')
        api_reset = api_rate.get('reset')
        time_zone = pytz.timezone('US/Pacific')
        reset = datetime.strftime(datetime.fromtimestamp(api_reset, time_zone), '%H:%M:%S')
        if api_remaining < api_threshold:
            now = datetime.strftime(datetime.now(time_zone), '%H:%M:%S')
            logger.info(f'API limit reset time: {reset}')
            logger.info(f'Time now: {now}')
            time_remaining = datetime.strptime(reset, '%H:%M:%S') - datetime.strptime(now, '%H:%M:%S')
            sleep_time = int(str(time_remaining).split(':')[1])
            if sleep_time > 10 and not prod_deploy:
                logger.error(f'Exiting as API limit ({api_remaining} remaining is < {api_threshold}) will not expire for {sleep_time} minutes. Please wait until {reset} to run jobs from this repository. See https://confluence-aes.kp.org/x/r8PuPQ for details.')
                exit(1)
            else:
                i = 0
                while i < sleep_time:
                    logger.error(f'Pausing for {sleep_time} minutes to allow API rate limit to reset. Will resume at {reset} PST. See https://confluence-aes.kp.org/x/r8PuPQ for details.')
                    time.sleep(60)
                    i += 1
        elif api_remaining < 150 and prod_deploy:
            logger.error(f'API rate limit remaining ({api_remaining} - reset at {reset} PST) could result in incomplete deployment. Setting output for check approval.')
            rate_limit_check_approval = {'remaining':api_remaining, 'reset':reset}
            os.system(f"echo 'rate-limit={json.dumps(rate_limit_check_approval)}' >> $GITHUB_OUTPUT")
        else:
            logger.info(f'API rate limit remaining ({api_remaining} - reset at {reset} PST) does not exceed threshold of < {api_threshold}.')
    except (RuntimeError, AttributeError) as e:
        logger.info(str(e))