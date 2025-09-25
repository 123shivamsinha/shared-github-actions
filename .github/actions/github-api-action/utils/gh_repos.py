import requests
import json
import os
import yaml
import json
import re
from kpghalogger import KpghaLogger
logger = KpghaLogger()

api_url = os.getenv('GITHUB_API_URL')
graphql_url = os.getenv('GITHUB_GRAPHQL_URL')
deploy_env = os.getenv('DEPLOY_ENV')
git_token = os.getenv('GHA_SVC_ACCOUNT')
input_repo = os.getenv('REPO')
gh_repo = os.getenv('GITHUB_REPOSITORY')
headers = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {git_token}",
    "Content-Type": "application/json" 
    }
ticket_details = yaml.safe_load(os.getenv('TICKET_DETAILS')) if os.getenv('TICKET_DETAILS') else None
repo = ticket_details.get('summary') if ticket_details else input_repo
app_type = ticket_details.get('intake-type') if ticket_details else os.getenv('APP_TYPE')
repo_org_name = ticket_details.get('project-org') if ticket_details else 'CDO-KP-ORG'


def update_environment():
    """
    Update the reviewers for the specified environments in a GitHub repository.

    This function retrieves the list of environments from the `deploy_env` variable,
    and updates the reviewers for each environment using the GitHub API.

    Args:
        None

    Returns:
        None
    """
    environments = yaml.safe_load(deploy_env)
    if isinstance(environments, str):
        envs = environments.split(',')
    else:
        envs = environments.get('envs')
    env_reviewers = []
    gh_teams = get_gh_teams(environments)
    logger.info(f'GH repo teams: {gh_teams}')
    for gh_team in gh_teams:
        env_reviewers.append({"type":"Team","id":gh_team})
    for env in envs:
        reqUrl = f"{api_url}/repos/{gh_repo}/environments/{env}"
        payload = json.dumps({
            "reviewers": env_reviewers
        })
        response = requests.request("PUT", reqUrl, data=payload,  headers=headers)
        logger.debug(response.text)


def update_apigee():
    """
    Update the reviewers for the Apigee environment in a GitHub repository.

    This function updates the reviewers for the Apigee environment using the GitHub API.

    Args:
        None

    Returns:
        None
    """
    # team name hardcoded for now as this is only use case
    if app_type.startswith('aks') and not re.search('-config$|-test-config', repo):
        logger.info(f"adding APIGEE GH team to the repo env settings")
        apigee_team = 2348
        req_url = f"{api_url}/repos/{repo_org_name}/{repo}/environments/{deploy_env}"
        payload = json.dumps({
        "reviewers": [
            {
            "type": "Team",
            "id": apigee_team
            }
        ]
        })
        response = requests.request("PUT", req_url, data=payload,  headers=headers)
        logger.info(f"updated apigee with status code: {response.status_code}")

def get_gh_teams(environments):
    """
    Get the GitHub teams associated with the repository.

    This function retrieves the GitHub teams associated with the repository using the GitHub API.

    Args:
        None

    Returns:
        List: A list of GitHub team IDs.
    """
    kporg_env_team = 2402
    kporg_release_engineers = 2400
    techlead_release_engineers = 2401
    gh_teams = []
    if gh_repo.endswith('aem-manifest'):
        gh_teams.append(kporg_env_team)
        gh_teams.append(kporg_release_engineers)
    elif "aks-canary-prod" in environments:
        gh_teams.append(kporg_release_engineers)
        gh_teams.append(techlead_release_engineers)
    else:
        reqUrl = f"{api_url}/repos/{gh_repo}/teams"
        response = requests.request("GET", reqUrl, headers=headers)
        gh_teams = [x.get('id') for x in response.json() if x.get('id') != 2348]
    return gh_teams