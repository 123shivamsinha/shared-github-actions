import os
import json
import yaml
import re
from github import Github, GithubException
from kpghalogger import KpghaLogger
logger = KpghaLogger()


def update_branch():
    """Update the branch with the latest changes from the repository."""
    try:
        repo_name = os.getenv('GITHUB_REPOSITORY')
        repo = repo_object(repo_name)
        file_path = 'aem-manifests'
        content = yaml.safe_load(os.getenv('RESULT_MAP') or '{}')
        file_content = json.dumps(content, indent=2)
        if not file_content:
            logger.error('Result map is empty or could not be read.')
            return

        file_name = content.get('manifest')
        if not file_name:
            logger.error(f'Manifest name not found in the content of {file_name}.')
            return
        
        update_branch = repo.default_branch
        repo_path = file_path + '/' +  file_name.upper() + '.json'
        logger.info(f'Pushing manifest to {repo_path}')
        push_to_scm(repo, repo_path, file_content, update_branch)

        # Support for combined manifests
        try:
            file_name_combined = file_name.split('.R')[0] if re.search(r'\.R[123]$', file_name) else file_name
            combined_manifests = {"test-artifacts": [], "products": [], "manifest": file_name_combined.upper()}
            combined_repo_path = file_path + '/' + file_name_combined.upper()
            contents = repo.get_contents(file_path)
            matching_files = [f for f in contents if f.name.startswith(file_name_combined.upper()) and f.name.endswith('.json')]
            if len(matching_files) < 2:
                return # No need to combine manifests if there's only one
            else: # Merge files into combined manifest
                for content_file in matching_files:
                    file_data = content_file.decoded_content.decode('utf-8')
                    file_json = json.loads(file_data)
                    combined_manifests["test-artifacts"].extend(file_json.get("test-artifacts", []))
                    combined_manifests["products"].extend(file_json.get("products", []))

                # Remove duplicates from both lists
                combined_manifests["test-artifacts"] = list(set(combined_manifests["test-artifacts"]))
                combined_manifests["products"] = list({json.dumps(d, sort_keys=True): d for d in combined_manifests["products"]}.values())
            
            # Write combined manifest to SCM
            combined_file_content = json.dumps(combined_manifests, indent=2)
            combined_repo_path_full = combined_repo_path + '.json'
            logger.info(f'Pushing combined manifest to {combined_repo_path_full}')
            push_to_scm(repo, combined_repo_path_full, combined_file_content, update_branch)
        except (GithubException, Exception) as e:
            logger.error(f'Error retrieving files from {file_path}: {e}')
    except Exception as e:
        raise Exception(f'Exception in extension action: {e}')


def repo_object(repo_name):
    auth_token = os.getenv('GHA_SVC_ACCOUNT') or os.getenv('APP_TOKEN')
    api_url = os.getenv('GITHUB_API_URL')
    github = Github(base_url=api_url, login_or_token=auth_token)
    repo = github.get_repo(repo_name)
    return repo


def push_to_scm(repo, repo_path, file_content, update_branch):
    try:
        update_branch = repo.get_branch(update_branch)
        update_repo_content(repo, update_branch.name, repo_path, file_content)
    except GithubException as e:
        logger.error(f"Error in pushing extension jobs: Will retry 1 more time. {e}")
    except RuntimeError as e:
        raise RuntimeError(f'Error in creating extension jobs on branch: {e}')


def update_repo_content(repo, branch, repo_path, file_content):
    build_url = os.getenv('BUILD_URL')
    file_name = repo_path.split('/')[-1]
    try:
        existing_content = repo.get_contents(repo_path, ref=branch)
        logger.info(f'Updating file {repo_path} on branch {branch}')
        repo.update_file(repo_path, f'Update {file_name} from {build_url}', file_content, sha=existing_content.sha, branch=branch)
    except GithubException as e:
        logger.info(f'File {repo_path} not found on branch {branch}, creating new file.')
        repo.create_file(repo_path, f'Create {file_name} from {build_url}', file_content, branch=branch)
    except Exception as e:
        logger.error(f'Updating file {repo_path} on branch {branch}: {e}')
