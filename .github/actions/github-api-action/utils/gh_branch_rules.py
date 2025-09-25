import requests
import os
import json
from kpghalogger import KpghaLogger
logger = KpghaLogger()

base_ref = os.getenv('TARGET_BRANCH') or os.getenv('BRANCH')
branch_only = os.getenv('BRANCH_ONLY')
api_url = os.getenv('GITHUB_API_URL')
app_type = os.getenv('APP_TYPE')
delete_hook = os.getenv('DELETE_HOOKS')
operation = os.getenv('OPERATION')
content_type_value = 'application/json'
accept_value = 'application/vnd.github.v3+json'
git_token = os.getenv('APP_TOKEN') if (os.getenv('APP_TOKEN') and 'aks-canary' not in operation) else os.getenv('GHA_SVC_ACCOUNT')
api_headers = {
    'Accept': accept_value,
    'Content-Type': content_type_value,
    'Authorization': f'Bearer {git_token}'
}


def create_gha_branch_rule(pr_check=False):
    delete_hooks = True if delete_hook == 'true' else False
    repo_name = os.getenv('REPO','').strip()
    if repo_name:
        repo_org = os.getenv('REPO_ORG').strip()
        repo = f'{repo_org}/{repo_name}'
        
    elif "aks-canary" in operation:
        repo_name = "service-discovery"
        repo_org = "CDO-KP-ORG"
    else:
        repo = os.getenv('GITHUB_REPOSITORY')
        repo_org = repo.split('/')[0]
        repo_name = repo.split('/')[1]
    # hardcoding response for service-discovery to reduce API calls
    if repo_name == "service-discovery":
        response = {"data": {"organization": {"id": "MDEyOk9yZ2FuaXphdGlvbjIzNjU=", "repository": {"id": "MDEwOlJlcG9zaXRvcnk0NTM4Mg==", "branchProtectionRules": {"nodes": [{"pattern": "release/*", "id": "MDIwOkJyYW5jaFByb3RlY3Rpb25SdWxlMjg3MzU=", "requiredStatusCheckContexts": []}]}}}}}
    else:
        response = repository_id(repo_org, repo_name).json()
    check_branch_protections(response, repo_org, repo_name)
    if not pr_check and repo_name != "service-discovery":
        delete_repo_hooks(repo_org, repo_name, delete_hooks)


def repository_id(repo_org, repo_name):
    query = f"""
    query {{
        organization(login: "{repo_org}") {{
            id
            repository(name: "{repo_name}") {{
                id
                branchProtectionRules(first:5){{
                    nodes {{
                        pattern
                        id
                        requiredStatusCheckContexts
                    }}
                }}
            }}
        }}
    }}
    """
    response = run_query(query)
    logger.info(f"Repository_id response {response}")
    return response


def run_query(query):
    try:
        headers = {
            'Content-Type': content_type_value,
            'Authorization': f"Bearer {git_token}"
        }
        request = requests.post('https://github.kp.org/api/graphql', json={'query': query}, headers=headers)
        logger.info(f"run_query response {request.json()}")
        return request
    except RuntimeError as e:
        raise RuntimeError(f'Error setting rules: {e}') from e


def update_branch_protection_rule(rule_id, check_contexts):
    admin_enforced, requires_status_checks, required_status_check = get_admin_required_status(check_contexts)
    logger.info (f"admin enforced value: {admin_enforced} required status checks: {required_status_check}, requires_status_checks: {requires_status_checks}")
    query = f"""
    mutation {{
        updateBranchProtectionRule(input: {{
            branchProtectionRuleId: "{rule_id}"
            dismissesStaleReviews: true
            isAdminEnforced: {admin_enforced}
            {required_status_check}
            requiresCodeOwnerReviews: {admin_enforced}
            requiresApprovingReviews: {admin_enforced}
            requiredApprovingReviewCount: 1
            requiresStatusChecks: {requires_status_checks}
        }})
        {{
            branchProtectionRule {{
            pattern
            }}
        }}
    }}
    """
    logger.info(f"query for updating branch protection rule for release branch: {query}")
    response = run_query(query)
    if response.status_code == 200:
        branch_pattern = response.json()['data']['updateBranchProtectionRule']['branchProtectionRule']['pattern']
        logger.info(f'Branch protection for {branch_pattern} branch updated successfully')
    else:
        logger.error(f'Error updating protection rule: {response.json()}')

def get_admin_required_status(check_contexts):
    if operation.startswith("update-branch-rule"):
        admin_enforced = "false"
    else:
        admin_enforced = "true"

    # don't set status checks in service-discovery repo
    if "aks-canary" in operation or admin_enforced == "false":
        required_status_check = ""
        requires_status_checks = "false"
    else:
        required_status_check = f"requiredStatusChecks: {check_contexts}"
        requires_status_checks = "true"
    return admin_enforced, requires_status_checks, required_status_check

def update_branch_protection_rule_aks_canary(rule_id, check_contexts):
    admin_enforced, requires_status_checks, required_status_check = get_admin_required_status(check_contexts)
    logger.info (f"admin enforced value: {admin_enforced} required status checks: {required_status_check}, requires_status_checks: {requires_status_checks}")
    query = f"""
    mutation {{
        updateBranchProtectionRule(input: {{
            branchProtectionRuleId: "{rule_id}"
            dismissesStaleReviews: true
            isAdminEnforced: {admin_enforced}
            {required_status_check}
            requiresCodeOwnerReviews: {admin_enforced}
            requiresApprovingReviews: {admin_enforced}
            requiredApprovingReviewCount: 1
            requiresStatusChecks: {requires_status_checks}
        }})
        {{
            branchProtectionRule {{
            pattern
            }}
        }}
    }}
    """
    logger.info(f"update_branch_protection_rule_aks_canary query to be run: {query}")
    response = run_query(query)
    if response.status_code == 200:
        branch_pattern = response.json()['data']['updateBranchProtectionRule']['branchProtectionRule']['pattern']
        logger.info(f'Branch protection for {branch_pattern} branch updated successfully')
    else:
        logger.error(f'Error updating protection rule: {response.json()}')
     

def create_branch_protection_rule(repository_id, pattern, check_contexts):
    query = f"""
    mutation {{
        createBranchProtectionRule(input: {{
            repositoryId: "{repository_id}"
            pattern: "{pattern}"
            isAdminEnforced: true
            dismissesStaleReviews: true
            requiresCodeOwnerReviews: true
            requiresApprovingReviews: true
            requiredApprovingReviewCount: 1
            requiresStatusChecks: true
            requiredStatusChecks: {check_contexts}
        }})
        {{
            branchProtectionRule {{
            pattern
            }}
        }}
    }}
    """
    response = run_query(query)
    if response.status_code == 200:
        branch_pattern = response.json()['data']['createBranchProtectionRule']['branchProtectionRule']['pattern']
        logger.info(f'Branch protection for {branch_pattern} branch created successfully')
    else:
        logger.error(f'Error creating protection rule: {response.json()}')
       

def check_branch_protections(response, repo_org, repo_name):
    try:
        repository_id = response['data']['organization']['repository']['id']
        branch_rules = response['data']['organization']['repository']['branchProtectionRules']['nodes']
        enforced_branches = [ branch.get('pattern') for branch in branch_rules ]
        check_context_map = {}
        
        if repo_name == "service-discovery":
            enforce_branches = ['release/*']
        else:
            enforce_branches = ['master', 'develop', 'release/*']
        delete_rules = list(set(enforced_branches).difference(enforce_branches))
        logger.info(f'Enforced branches: {enforced_branches}')
        logger.info(f'Delete rules from branches: {delete_rules}')

        if repo_name.endswith('-test-config'):
            check_contexts = []               
        else:
            check_contexts = ['GHA PR Check Status']
            check_context_map[check_contexts[0]] = ""
        # todo add nexus status check
        # if not config_repo:
        #     check_contexts.insert(0,'IQ Policy Evaluation')
        #     check_context_map[check_contexts[0]] = "any"
        
        # form context string for mutation
        check_context_str = "["
        for k,v in check_context_map.items():
            check_context_str += f"{{context: \"{k}\" appId: \"{v}\"}}"
        check_context_str += "]"
        create_rules = list(set(enforce_branches).difference(enforced_branches))
        if branch_rules and len(branch_rules) > 0:
            for rule in branch_rules:
                if rule.get('pattern') in enforce_branches:
                    required_checks = rule.get('requiredStatusCheckContexts')
                    rule_id = rule.get('id')
                    rule_branch = rule.get('pattern')
                    if "update-branch-rule" in operation:
                        if 'aks-canary' in operation:
                            update_branch_protection_rule_aks_canary(rule_id, check_context_str)
                        elif 'release' not in rule_branch :
                            update_rest_api_branch_protection_rule(repo_org, rule_branch, repo_name, check_contexts, rule_id)
                        else:
                            update_branch_protection_rule(rule_id, check_context_str)
                    elif sorted(required_checks) != sorted(check_contexts):
                        update_branch_protection_rule(rule_id, check_context_str)
                    else:
                        logger.error(f"Branch protection rules correct for branch: {rule_branch}, update not needed")
        for create_rule in create_rules:
            create_branch_protection_rule(repository_id, create_rule, check_context_str)
        for delete_rule in delete_rules:
            delete_branch_protection_rule(repo_org, repo_name, delete_rule)
    except RuntimeError as e:
        logger.error(f'Error creating branch rules: {e}')
        

def delete_branch_protection_rule(repo_org, repo_name, branch):
    try:
        url = f'{api_url}/repos/{repo_org}/{repo_name}/branches/{branch}/protection'
        response = requests.request("DELETE", url, headers=api_headers)
        logger.info(f"delete_branch_protection_rule {response.status_code}")
    except RuntimeError as e:
        logger.error(f'Error deleting stale rules: {e}')
        

def delete_repo_hooks(repo_org, repo_name, delete_hooks):
    try:
        url = f'{api_url}/repos/{repo_org}/{repo_name}/hooks'
        webhooks = []
        response = requests.request("GET", url, headers=api_headers)
        repo_hooks = json.loads(response.text)
        for repo_hook in repo_hooks:
            if 'jenkins' in repo_hook.get('config').get('url') and repo_hook.get('active'):
                webhooks.append(repo_hook.get('id'))
        logger.info(f'Active jenkins webhooks: {webhooks}')
    except RuntimeError as e:
        logger.error(f'Error fetching webhooks for repo {repo_name}: {e}')
        
    for webhook in webhooks:
        try:
            logger.info(f'Disabling webhook {webhook}')
            url = f'{api_url}/repos/{repo_org}/{repo_name}/hooks/{webhook}'

            payload = json.dumps({
                "active": False
            })
            if delete_hooks: response = requests.request("DELETE", url, headers=api_headers, data=payload)
            else: response = requests.request("PATCH", url, headers=api_headers, data=payload)
            logger.info(f"delete_repo_hooks {response.text}")
        except RuntimeError as e:
            logger.error(f'Error disabling webhook {webhook}: {e}')


def update_rest_api_branch_protection_rule(repo_org, branch, repo_name, check_contexts, rule_id):
    try:
        if operation.startswith("update-branch-rule"):
            admin_enforced = False
        else:
            admin_enforced = True
        # don't set status checks in service-discovery repo
        if "aks-canary" in operation or admin_enforced == "false":
            required_status_check = ""
            requires_status_checks = False
        else:
            required_status_check = check_contexts
            requires_status_checks = True
        logger.info(f"admin enforced value: {admin_enforced} required status checks: {required_status_check}, requires_status_checks: {requires_status_checks}")
        url = f'{api_url}/repos/{repo_org}/{repo_name}/branches/{branch}/protection'
        data = json.dumps({"require_approving_reviews": admin_enforced, 
                "requires_status_checks": requires_status_checks, 
                "branch_protection_rule_id": rule_id,
                "enforce_admins": admin_enforced,
                "required_pull_request_reviews": {
                    "dismiss_stale_reviews": True,
                    "require_code_owner_reviews": admin_enforced,
                    "required_approving_review_count": 1
                },
                "required_status_checks": {
                    "strict": admin_enforced,
                    "contexts": required_status_check
                },
                "restrictions": None
            })
        logger.info(f"paylod : {data}, url: {url}")
        response = requests.request("PUT", url, data=data, headers=api_headers)
        logger.info(f"status code response for update api: {response.status_code}")
        if response.status_code == 200:
            logger.info(f'Updated branch protection rules successfully')
        else:
            logger.error((f'Error Updated branch protection rules for the  {branch} branch.'))
    except RuntimeError as e:
        logger.error(f'Error Updating branch protection rules: {e}')