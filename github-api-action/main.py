import os
import time
import subprocess
from utils import gh_prcheck
from utils import gh_cli
from utils import gh_repos
from utils import gh_branch_rules
from utils import gh_utils
from urllib.parse import urlparse
from kpghalogger import KpghaLogger

logger = KpghaLogger()
operation = os.getenv('OPERATION')
pr_branch = os.getenv('GITHUB_HEAD_REF')
COLOR_RED = "\u001b[31m"


def main():
    if operation == 'deployment-validation':
        gh_cli.check_workflow("Deployment Validation")
    elif operation == 'regression':
        gh_cli.regression()
    elif operation == 'cross-browser':
        gh_cli.cross_browser()  
    elif operation == 'update-secrets':
        gh_cli.update_secrets()
    elif operation == 'check-secrets':
        gh_cli.check_secrets()
    elif operation == 'rate-limit':
        gh_cli.rate_limit()
    elif operation == 'pr-info':
        gh_prcheck.get_info()
    elif operation == 'pr-comment':
        gh_prcheck.pr_comment()        
    elif operation == 'change-set':
        gh_prcheck.change_set()
    elif operation == 'update-status':
        gh_prcheck.update_status()
    elif operation == 'environment-approval':
        gh_repos.update_environment()
    elif operation == 'apigee-approval':
        gh_repos.update_apigee()
    elif operation == 'update-repo' or "update-branch-rule" in operation:
        pr_check = True if pr_branch else False
        gh_branch_rules.create_gha_branch_rule(pr_check)
    elif operation == 'extension-job':
        gh_cli.extension_job()
    elif operation == 'update-branch':
        gh_utils.update_branch()
    elif operation == 'gha-login':
        login_gha()     


def set_result():
    git_result = os.getenv('GITHUB_RESULT')
    jenkins_result = os.getenv('JENKINS_RESULT')
    test_result = git_result or jenkins_result

    git_url = os.getenv('GITHUB_URL')
    jenkins_url = os.getenv('JENKINS_URL')
    test_url = git_url or jenkins_url

    os.system(f"echo 'test-url={test_url}' >> $GITHUB_OUTPUT")
    os.system(f"echo 'test-result={test_result}' >> $GITHUB_OUTPUT")

def login_gha():
    server_url = os.getenv('GITHUB_SERVER_URL')
    parsed_url = urlparse(server_url)
    hostname = parsed_url.hostname
    for i in range(1, 11):
        try:
            logger.info(f"Attempting to login to GitHub CLI for the {i} time.")
            if os.getenv('GHA_ORG') == 'ENTERPRISE':
                subprocess.run(
                    ["gh", "auth", "login", "--hostname", hostname, "--with-token"],
                    text=True,
                    check=True,
                    timeout=30
                )
            else:
                subprocess.run(
                    ["gh", "auth", "login", "--hostname", hostname, "--with-token"],
                    input=os.getenv('GHA_SVC_ACCOUNT'),
                    text=True,
                    check=True,
                    timeout=30
                )
            break
        except subprocess.TimeoutExpired:
            logger.info(f"Process timed out after 30 seconds.")
        if i == 10:
            raise Exception(f"{COLOR_RED} Failed to login to GitHub CLI after 10 attempts.")    
    
    
if __name__ == '__main__':
  logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "start"}}))
  main()
  logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))